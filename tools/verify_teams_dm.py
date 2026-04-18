"""
Microsoft Graph API — Teams DM送信 検証スクリプト

確認項目:
1. Azure AD アクセストークン取得（Client Credentials Flow）
2. 対象ユーザーのオブジェクトID取得
3. アプリのサービスプリンシパルID取得
4. 1:1チャットの作成
5. テキストメッセージ送信
6. Adaptive Card送信（本番想定フォーマット）

使い方:
  python verify_teams_dm.py \\
    --tenant-id YOUR_TENANT_ID \\
    --client-id YOUR_CLIENT_ID \\
    --client-secret YOUR_CLIENT_SECRET \\
    --target-email TARGET_USER_EMAIL

事前準備（Azure Portal）:
  1. Microsoft Entra ID → アプリの登録 → 新規登録
  2. API のアクセス許可 → アプリケーション権限で以下を追加:
     - Chat.Create
     - ChatMessage.Send
     - User.Read.All
  3. 「管理者の同意を与えます」ボタンをクリック
  4. 証明書とシークレット → クライアントシークレット生成
"""

import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("[エラー] requests が未インストールです。以下を実行してください:")
    print("  pip install requests")
    sys.exit(1)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# 検証用 Adaptive Card サンプル（本番と同じフォーマット）
SAMPLE_ADAPTIVE_CARD = {
    "type": "AdaptiveCard",
    "version": "1.5",
    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
    "body": [
        {
            "type": "TextBlock",
            "size": "Medium",
            "weight": "Bolder",
            "text": "⚠ 勤怠・工数 差異検出【テスト送信】"
        },
        {
            "type": "TextBlock",
            "text": "このメッセージは Graph API 検証スクリプトからの **テスト送信** です。",
            "wrap": True
        },
        {
            "type": "TextBlock",
            "text": "対象期間: 2026/04/01 〜 2026/04/14"
        },
        {
            "type": "Table",
            "columns": [{"width": 2}, {"width": 1}, {"width": 1}, {"width": 1}],
            "rows": [
                {
                    "type": "TableRow",
                    "style": "accent",
                    "cells": [
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "日付", "weight": "Bolder"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "勤怠", "weight": "Bolder"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "工数", "weight": "Bolder"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "差異", "weight": "Bolder"}]}
                    ]
                },
                {
                    "type": "TableRow",
                    "cells": [
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "4/01(水)"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "8:00"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "7:30"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "+0:30", "color": "Attention"}]}
                    ]
                },
                {
                    "type": "TableRow",
                    "cells": [
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "4/03(金)"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "8:00"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "0:00"}]},
                        {"type": "TableCell", "items": [{"type": "TextBlock", "text": "+8:00", "color": "Attention"}]}
                    ]
                }
            ]
        },
        {
            "type": "TextBlock",
            "text": "⚠ 15分以上の差異がある日のみ表示しています",
            "color": "Warning",
            "wrap": True
        }
    ]
}


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_response(resp: requests.Response, step: str) -> dict:
    """レスポンスチェック（HTTP 200でもエラー文字列を検出）"""
    body_text = resp.text
    if resp.status_code >= 400:
        print(f"[{step}] ✗ HTTP {resp.status_code}", file=sys.stderr)
        try:
            err = resp.json()
            code = err.get("error", {}).get("code", "")
            msg = err.get("error", {}).get("message", body_text)
            print(f"[{step}]   エラーコード: {code}", file=sys.stderr)
            print(f"[{step}]   メッセージ: {msg}", file=sys.stderr)
            # 権限不足の場合に追加案内
            if resp.status_code == 403 or code in ("Forbidden", "Authorization_RequestDenied"):
                print(f"\n[{step}] ヒント: 権限不足の可能性があります。以下を確認してください:", file=sys.stderr)
                print(f"  - Azure Portal → アプリ → API のアクセス許可", file=sys.stderr)
                print(f"  - Chat.Create / ChatMessage.Send / User.Read.All が「許可されました」になっているか", file=sys.stderr)
                print(f"  - 「管理者の同意を与えます」を実行済みか", file=sys.stderr)
            elif resp.status_code == 404:
                print(f"\n[{step}] ヒント: リソースが見つかりません。メールアドレスを確認してください。", file=sys.stderr)
        except Exception:
            print(f"[{step}]   レスポンス: {body_text[:200]}", file=sys.stderr)
        sys.exit(1)

    # HTTP 200でもエラー文字列が含まれるケースへの対策
    if any(kw in body_text.lower() for kw in ["\"error\"", "failed", "unauthorized"]):
        try:
            data = resp.json()
            if "error" in data:
                print(f"[{step}] ✗ HTTP 200 だがエラーレスポンス検出: {data}", file=sys.stderr)
                sys.exit(1)
        except Exception:
            pass

    return resp.json() if resp.text else {}


# ─────────────────────────────────────────────
# Step 1: アクセストークン取得
# ─────────────────────────────────────────────
def get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    print("\n[Step 1] アクセストークン取得...")
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    resp = requests.post(url, data=data)
    result = check_response(resp, "Step 1")
    expires_in = result.get("expires_in", "不明")
    print(f"[Step 1] ✓ トークン取得成功（expires_in: {expires_in}秒）")
    return result["access_token"]


# ─────────────────────────────────────────────
# Step 2: 対象ユーザーのオブジェクトID取得
# ─────────────────────────────────────────────
def get_user_object_id(token: str, email: str) -> tuple[str, str]:
    print(f"\n[Step 2] 対象ユーザー情報取得: {email}")
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{GRAPH_BASE}/users/{email}", headers=headers)
    result = check_response(resp, "Step 2")
    user_id = result["id"]
    display_name = result.get("displayName", "不明")
    print(f"[Step 2] ✓ ユーザーID: {user_id}")
    print(f"[Step 2]   表示名: {display_name}")
    return user_id, display_name


# ─────────────────────────────────────────────
# Step 3: アプリのサービスプリンシパルID取得
# ─────────────────────────────────────────────
def get_service_principal_id(token: str, client_id: str) -> str:
    print(f"\n[Step 3] サービスプリンシパルID取得...")
    headers = {"Authorization": f"Bearer {token}"}
    params = {"$filter": f"appId eq '{client_id}'", "$select": "id,displayName"}
    resp = requests.get(f"{GRAPH_BASE}/servicePrincipals", headers=headers, params=params)
    result = check_response(resp, "Step 3")
    values = result.get("value", [])
    if not values:
        print("[Step 3] ✗ サービスプリンシパルが見つかりません", file=sys.stderr)
        print("  アプリがエンタープライズアプリとして登録されているか確認してください", file=sys.stderr)
        sys.exit(1)
    sp_id = values[0]["id"]
    sp_name = values[0].get("displayName", "不明")
    print(f"[Step 3] ✓ SP ID: {sp_id}")
    print(f"[Step 3]   アプリ名: {sp_name}")
    return sp_id


# ─────────────────────────────────────────────
# Step 4: 1:1チャットの作成
# ─────────────────────────────────────────────
def create_or_get_chat(token: str, user_object_id: str, sp_id: str) -> str:
    print(f"\n[Step 4] 1:1チャット作成...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "chatType": "oneOnOne",
        "members": [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_object_id}')"
            },
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{sp_id}')"
            }
        ]
    }
    resp = requests.post(f"{GRAPH_BASE}/chats", headers=headers, json=body)

    # 409 = チャットが既に存在する場合は取得
    if resp.status_code == 409:
        print("[Step 4]   既存チャットを検出、取得を試みます...")
        try:
            existing = resp.json()
            chat_id = existing.get("error", {}).get("innerError", {}).get("value")
            if chat_id:
                print(f"[Step 4] ✓ 既存チャットID: {chat_id}")
                return chat_id
        except Exception:
            pass

    result = check_response(resp, "Step 4")
    chat_id = result["id"]
    print(f"[Step 4] ✓ チャットID: {chat_id}")
    return chat_id


# ─────────────────────────────────────────────
# Step 5: テキストメッセージ送信
# ─────────────────────────────────────────────
def send_text_message(token: str, chat_id: str) -> str:
    print(f"\n[Step 5] テキストメッセージ送信...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "body": {
            "content": "【テスト】Graph API接続確認メッセージ（勤怠工数通知システム検証スクリプトより）"
        }
    }
    resp = requests.post(f"{GRAPH_BASE}/chats/{chat_id}/messages", headers=headers, json=body)
    result = check_response(resp, "Step 5")
    msg_id = result.get("id", "不明")
    print(f"[Step 5] ✓ 送信成功（message-id: {msg_id}）")
    return msg_id


# ─────────────────────────────────────────────
# Step 6: Adaptive Card送信
# ─────────────────────────────────────────────
def send_adaptive_card(token: str, chat_id: str) -> str:
    print(f"\n[Step 6] Adaptive Card送信（本番想定フォーマット）...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "body": {
            "contentType": "html",
            "content": "<attachment id=\"card1\"></attachment>"
        },
        "attachments": [
            {
                "id": "card1",
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": json.dumps(SAMPLE_ADAPTIVE_CARD)
            }
        ]
    }
    resp = requests.post(f"{GRAPH_BASE}/chats/{chat_id}/messages", headers=headers, json=body)
    result = check_response(resp, "Step 6")
    msg_id = result.get("id", "不明")
    print(f"[Step 6] ✓ 送信成功（message-id: {msg_id}）")
    return msg_id


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Microsoft Graph API Teams DM送信 検証スクリプト"
    )
    parser.add_argument("--tenant-id", required=True, help="Azure AD テナントID")
    parser.add_argument("--client-id", required=True, help="Azure AD アプリ クライアントID")
    parser.add_argument("--client-secret", required=True, help="Azure AD クライアントシークレット")
    parser.add_argument("--target-email", required=True, help="送信先メールアドレス（テスト用: 自分のメールアドレスを推奨）")
    args = parser.parse_args()

    print_section("Graph API Teams DM 送信検証")
    print(f"  対象: {args.target_email}")

    results = {}

    try:
        # Step 1: トークン取得
        token = get_access_token(args.tenant_id, args.client_id, args.client_secret)
        results["Step 1 トークン取得"] = "✓ 成功"

        # Step 2: ユーザーID取得
        user_id, display_name = get_user_object_id(token, args.target_email)
        results["Step 2 ユーザーID取得"] = f"✓ 成功（{display_name}）"

        # Step 3: サービスプリンシパルID取得
        sp_id = get_service_principal_id(token, args.client_id)
        results["Step 3 SP ID取得"] = "✓ 成功"

        # Step 4: チャット作成
        chat_id = create_or_get_chat(token, user_id, sp_id)
        results["Step 4 チャット作成"] = "✓ 成功"

        # 連続リクエスト対策で少し待機
        time.sleep(0.5)

        # Step 5: テキストメッセージ送信
        send_text_message(token, chat_id)
        results["Step 5 テキスト送信"] = "✓ 成功"

        time.sleep(0.5)

        # Step 6: Adaptive Card送信
        send_adaptive_card(token, chat_id)
        results["Step 6 Adaptive Card送信"] = "✓ 成功"

    except SystemExit:
        print_section("検証結果サマリー")
        for step, status in results.items():
            print(f"  {step}: {status}")
        print("\n  → 途中でエラーが発生しました。上記のエラーメッセージを確認してください。")
        sys.exit(1)

    # Step 7: サマリー
    print_section("検証結果サマリー")
    for step, status in results.items():
        print(f"  {step}: {status}")
    print(f"\n  全{len(results)}ステップ: 成功 ✓")
    print(f"  → Teams DM送信（Graph API）は実装可能です")
    print(f"\n  Teamsアプリで {args.target_email} のチャットを確認してください。")
    print(f"  テキストメッセージとAdaptive Cardの2件が届いているはずです。")


if __name__ == "__main__":
    main()

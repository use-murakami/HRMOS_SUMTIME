"""
Microsoft Graph API — メール送信 検証スクリプト

確認項目:
1. Azure AD アクセストークン取得（Client Credentials Flow）
2. テキストメール送信
3. HTML表形式メール送信（本番想定フォーマット）

使い方:
  python verify_email.py \\
    --tenant-id YOUR_TENANT_ID \\
    --client-id YOUR_CLIENT_ID \\
    --client-secret YOUR_CLIENT_SECRET \\
    --sender-email SENDER_EMAIL \\
    --target-email TARGET_USER_EMAIL

事前準備（Azure Portal）:
  1. Microsoft Entra ID → アプリの登録
  2. API のアクセス許可 → アプリケーション権限:
     - Mail.Send
  3. 「管理者の同意を与えます」ボタンをクリック
"""

import argparse
import sys

try:
    import requests
except ImportError:
    print("[エラー] requests が未インストールです。以下を実行してください:")
    print("  pip install requests")
    sys.exit(1)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# 検証用HTMLメール本文（本番と同じフォーマット）
SAMPLE_HTML_BODY = """
<html>
<body style="font-family: sans-serif; font-size: 14px; color: #333;">

<p><strong>山田太郎 さん</strong></p>

<p>
以下の期間で勤怠時間と工数の差異が検出されました。<br>
ご確認のうえ、修正をお願いします。
</p>

<p><strong>対象期間: 2026/04/01 〜 2026/04/14</strong></p>

<table border="1" cellpadding="6" cellspacing="0"
       style="border-collapse: collapse; min-width: 360px;">
  <thead>
    <tr style="background-color: #4472C4; color: white;">
      <th>日付</th>
      <th>勤怠</th>
      <th>工数</th>
      <th>差異</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>4/01(水)</td>
      <td>8:00</td>
      <td>7:30</td>
      <td style="color: #C00000;"><strong>+0:30</strong></td>
    </tr>
    <tr style="background-color: #F2F2F2;">
      <td>4/03(金)</td>
      <td>8:00</td>
      <td>0:00</td>
      <td style="color: #C00000;"><strong>+8:00</strong></td>
    </tr>
  </tbody>
</table>

<p style="color: #C00000;">⚠ 15分以上の差異がある日のみ表示しています</p>
<p style="color: #888; font-size: 12px;">
  ※ 差異が解消されると通知は停止します<br>
  ※ このメールは自動送信です。返信は不要です。
</p>

</body>
</html>
"""


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_response(resp: requests.Response, step: str) -> dict:
    """レスポンスチェック"""
    if resp.status_code >= 400:
        print(f"[{step}] ✗ HTTP {resp.status_code}", file=sys.stderr)
        try:
            err = resp.json()
            code = err.get("error", {}).get("code", "")
            msg = err.get("error", {}).get("message", resp.text)
            print(f"[{step}]   エラーコード: {code}", file=sys.stderr)
            print(f"[{step}]   メッセージ: {msg}", file=sys.stderr)
            if resp.status_code == 403 or code in ("Forbidden", "Authorization_RequestDenied"):
                print(f"\n[{step}] ヒント: 権限不足の可能性があります。以下を確認してください:", file=sys.stderr)
                print(f"  - Azure Portal → アプリ → API のアクセス許可", file=sys.stderr)
                print(f"  - Mail.Send（アプリケーション）が「許可されました」になっているか", file=sys.stderr)
                print(f"  - 「管理者の同意を与えます」を実行済みか", file=sys.stderr)
        except Exception:
            print(f"[{step}]   レスポンス: {resp.text[:200]}", file=sys.stderr)
        sys.exit(1)
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
# Step 2: テキストメール送信（動作確認用）
# ─────────────────────────────────────────────
def send_text_mail(token: str, sender: str, target: str) -> None:
    print(f"\n[Step 2] テキストメール送信...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "message": {
            "subject": "【テスト】Graph API メール送信確認（勤怠工数通知システム）",
            "body": {
                "contentType": "Text",
                "content": "このメールはGraph API検証スクリプトからのテスト送信です。\n正常に受信できていれば、メール通知機能は動作しています。"
            },
            "toRecipients": [
                {"emailAddress": {"address": target}}
            ]
        }
    }
    resp = requests.post(
        f"{GRAPH_BASE}/users/{sender}/sendMail",
        headers=headers,
        json=body
    )
    # sendMail は成功時 HTTP 202 を返す（レスポンスボディなし）
    if resp.status_code == 202:
        print(f"[Step 2] ✓ 送信成功（HTTP 202 Accepted）")
    else:
        check_response(resp, "Step 2")


# ─────────────────────────────────────────────
# Step 3: HTML表形式メール送信（本番想定フォーマット）
# ─────────────────────────────────────────────
def send_html_mail(token: str, sender: str, target: str) -> None:
    print(f"\n[Step 3] HTML表形式メール送信（本番想定フォーマット）...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "message": {
            "subject": "【勤怠・工数差異】確認をお願いします【テスト送信】",
            "body": {
                "contentType": "HTML",
                "content": SAMPLE_HTML_BODY
            },
            "toRecipients": [
                {"emailAddress": {"address": target}}
            ]
        }
    }
    resp = requests.post(
        f"{GRAPH_BASE}/users/{sender}/sendMail",
        headers=headers,
        json=body
    )
    if resp.status_code == 202:
        print(f"[Step 3] ✓ 送信成功（HTTP 202 Accepted）")
    else:
        check_response(resp, "Step 3")


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Microsoft Graph API メール送信 検証スクリプト"
    )
    parser.add_argument("--tenant-id",     required=True, help="Azure AD テナントID")
    parser.add_argument("--client-id",     required=True, help="Azure AD アプリ クライアントID")
    parser.add_argument("--client-secret", required=True, help="Azure AD クライアントシークレット")
    parser.add_argument("--sender-email",  required=True, help="送信元メールアドレス（テナント内の実在ユーザー）")
    parser.add_argument("--target-email",  required=True, help="送信先メールアドレス（テスト用: 自分のメールアドレスを推奨）")
    args = parser.parse_args()

    print_section("Graph API メール送信検証")
    print(f"  送信元: {args.sender_email}")
    print(f"  送信先: {args.target_email}")

    results = {}

    try:
        # Step 1: トークン取得
        token = get_access_token(args.tenant_id, args.client_id, args.client_secret)
        results["Step 1 トークン取得"] = "✓ 成功"

        # Step 2: テキストメール送信
        send_text_mail(token, args.sender_email, args.target_email)
        results["Step 2 テキストメール送信"] = "✓ 成功"

        # Step 3: HTML表形式メール送信
        send_html_mail(token, args.sender_email, args.target_email)
        results["Step 3 HTMLメール送信"] = "✓ 成功"

    except SystemExit:
        print_section("検証結果サマリー")
        for step, status in results.items():
            print(f"  {step}: {status}")
        print("\n  → 途中でエラーが発生しました。上記のエラーメッセージを確認してください。")
        sys.exit(1)

    # サマリー
    print_section("検証結果サマリー")
    for step, status in results.items():
        print(f"  {step}: {status}")
    print(f"\n  全{len(results)}ステップ: 成功 ✓")
    print(f"  → Graph API メール送信は実装可能です")
    print(f"\n  {args.target_email} のメールボックスを確認してください。")
    print(f"  テキストメールとHTML表形式メールの2件が届いているはずです。")


if __name__ == "__main__":
    main()

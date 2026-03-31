"""
HRMOS勤怠 APIレスポンス確認スクリプト

確認項目:
1. actual_working_hours の値と形式
2. segment_display_title の実際の値（勤務区分の表記）
3. email フィールドの有無と値
4. 時間フィールドの形式（"H:MM" or "HH:MM" or その他）

使い方:
  python verify_api.py --company-url YOUR_COMPANY_URL --secret-key YOUR_SECRET_KEY
"""

import argparse
import base64
import json
import requests
import sys
from datetime import datetime


def make_base_url(company_url: str) -> str:
    return f"https://ieyasu.co/api/{company_url}/v1"


def get_token(base_url: str, secret_key: str) -> str:
    """Step 1: トークン取得（3パターンを順に試行）"""
    url = f"{base_url}/authentication/token"

    # パターン1: secret_key: (標準Basic認証)
    # パターン2: secret_keyをそのままBase64
    # パターン3: secret_keyを直接使用 (既にBase64の場合)
    patterns = [
        ("secret_key:", base64.b64encode(f"{secret_key}:".encode()).decode()),
        ("secret_key Base64", base64.b64encode(secret_key.encode()).decode()),
        ("secret_key 直接", secret_key),
    ]

    for name, encoded in patterns:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded}",
        }
        print(f"[認証] 試行: {name}")
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[認証] 成功パターン: {name}")
            print(f"[認証] トークン取得成功 (有効期限: {data.get('expired_at', '不明')})")
            return data["token"]
        print(f"[認証] → HTTP {resp.status_code}")

    # デバッグ情報
    print(f"\n[認証] すべて失敗しました")
    print(f"[認証] URL: {url}")
    print(f"[認証] Secret Key 長さ: {len(secret_key)}文字")
    print(f"[認証] Secret Key 先頭3文字: {secret_key[:3]}...")
    sys.exit(1)
    data = resp.json()
    print(f"[認証] トークン取得成功 (有効期限: {data.get('expired_at', '不明')})")
    return data["token"]


def fetch_work_outputs(base_url: str, token: str, month: str, limit: int = 5) -> list:
    """Step 2: 勤怠データ取得（先頭数件のみ）"""
    url = f"{base_url}/work_outputs/monthly/{month}"
    headers = {"Authorization": f"Token {token}"}
    params = {"limit": limit, "page": 1}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()

    total_count = resp.headers.get("X-Total-Count", "不明")
    total_page = resp.headers.get("X-Total-Page", "不明")
    print(f"[勤怠] 総件数: {total_count}, 総ページ: {total_page} (先頭{limit}件を取得)")

    return resp.json()


def fetch_users(base_url: str, token: str, limit: int = 5) -> list:
    """Step 3: ユーザー一覧取得（先頭数件のみ）"""
    url = f"{base_url}/users"
    headers = {"Authorization": f"Token {token}"}
    params = {"limit": limit, "page": 1}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()

    total_count = resp.headers.get("X-Total-Count", "不明")
    print(f"[ユーザー] 総件数: {total_count} (先頭{limit}件を取得)")

    return resp.json()


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def analyze_work_output(record: dict, index: int):
    """勤怠レコード1件の注目フィールドを表示"""
    print(f"\n--- レコード {index + 1} ---")
    fields = [
        ("number", "社員番号"),
        ("full_name", "氏名"),
        ("day", "日付"),
        ("segment_display_title", "勤務区分"),
        ("start_at", "出勤時刻"),
        ("end_at", "退勤時刻"),
        ("total_break_time", "休憩時間"),
        ("actual_working_hours", "実労働時間"),
        ("total_working_hours", "総労働時間"),
    ]
    for key, label in fields:
        value = record.get(key)
        print(f"  {label:　<8} ({key}): {value!r}")


def analyze_user(record: dict, index: int):
    """ユーザーレコード1件の注目フィールドを表示"""
    print(f"\n--- ユーザー {index + 1} ---")
    fields = [
        ("number", "社員番号"),
        ("last_name", "姓"),
        ("first_name", "名"),
        ("email", "メール"),
    ]
    for key, label in fields:
        value = record.get(key)
        print(f"  {label:　<6} ({key}): {value!r}")


def save_raw_response(data: dict, filename: str):
    """生レスポンスをJSONファイルに保存"""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → 生レスポンスを {filename} に保存しました")


def main():
    parser = argparse.ArgumentParser(description="HRMOS勤怠 APIレスポンス確認")
    parser.add_argument("--company-url", required=True, help="HRMOSログインURLの会社識別子")
    parser.add_argument("--secret-key", required=True, help="HRMOS API Secret Key")
    parser.add_argument("--month", default=None, help="対象月 (YYYY-MM形式、デフォルト: 今月)")
    parser.add_argument("--limit", type=int, default=5, help="取得件数 (デフォルト: 5)")
    parser.add_argument("--save-raw", action="store_true", help="生レスポンスをJSONファイルに保存")
    args = parser.parse_args()

    if args.month is None:
        args.month = datetime.now().strftime("%Y-%m")

    try:
        base_url = make_base_url(args.company_url)
        print(f"[設定] ベースURL: {base_url}")

        # 1. 認証
        print_section("1. トークン取得")
        token = get_token(base_url, args.secret_key)

        # 2. 勤怠データ
        print_section(f"2. 勤怠データ ({args.month})")
        work_outputs = fetch_work_outputs(base_url, token, args.month, args.limit)

        if work_outputs:
            for i, record in enumerate(work_outputs):
                analyze_work_output(record, i)

            if args.save_raw:
                save_raw_response(work_outputs, "raw_work_outputs.json")

            # segment_display_title の値一覧
            titles = set(r.get("segment_display_title") for r in work_outputs)
            print(f"\n[集計] 取得データ内の勤務区分一覧: {titles}")
        else:
            print("  データなし")

        # 3. ユーザー一覧
        print_section("3. ユーザー一覧")
        users = fetch_users(base_url, token, args.limit)

        if users:
            for i, record in enumerate(users):
                analyze_user(record, i)

            if args.save_raw:
                save_raw_response(users, "raw_users.json")

            # email の存在確認
            has_email = all(r.get("email") for r in users)
            print(f"\n[集計] 全ユーザーにemailあり: {has_email}")
        else:
            print("  データなし")

        # 4. 確認サマリー
        print_section("4. 確認サマリー")
        if work_outputs:
            sample = work_outputs[0]
            print(f"  actual_working_hours 存在: {'actual_working_hours' in sample}")
            print(f"  actual_working_hours 値例: {sample.get('actual_working_hours')!r}")
            print(f"  segment_display_title 存在: {'segment_display_title' in sample}")
            print(f"  segment_display_title 値例: {sample.get('segment_display_title')!r}")
            print(f"  時間形式の例: start_at={sample.get('start_at')!r}, total_break_time={sample.get('total_break_time')!r}")
        if users:
            sample = users[0]
            print(f"  email 存在: {'email' in sample}")
            print(f"  email 値例: {sample.get('email')!r}")

    except requests.HTTPError as e:
        print(f"\n[エラー] HTTP {e.response.status_code}: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[エラー] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

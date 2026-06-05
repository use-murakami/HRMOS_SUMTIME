"""
SUMTIME 単日明細チェックスクリプト（診断用）

指定ユーザー・指定日の working_achievements を1行ずつ表示し、
合計時間と突き合わせシステムが集計する値を確認する。

認証情報は Secret Manager の sumtime-credentials から取得する。

使い方:
  python tools/inspect_sumtime_day.py \
    --key-file office-pc-key.json \
    --project kintai-kosu-notification \
    --email y-murakami@use-eng.co.jp \
    --date 2026-05-01
"""
import argparse
import json
import os
import sys

try:
    from google.cloud import secretmanager
except ImportError:
    print("[エラー] google-cloud-secret-manager が未インストールです")
    sys.exit(1)
try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    print("[エラー] sshtunnel が未インストールです: pip install sshtunnel")
    sys.exit(1)
try:
    import psycopg2
except ImportError:
    print("[エラー] psycopg2 が未インストールです: pip install psycopg2-binary")
    sys.exit(1)


def load_sumtime_secret(project_id: str) -> dict:
    """Secret Manager の sumtime-credentials を取得して dict で返す。"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/sumtime-credentials/versions/latest"
    raw = client.access_secret_version(request={"name": name}).payload.data.decode("UTF-8")
    return json.loads(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="SUMTIME 単日明細チェック（診断用）")
    parser.add_argument("--key-file", required=True, help="GCPサービスアカウントキーのパス")
    parser.add_argument("--project",  required=True, help="GCPプロジェクトID")
    parser.add_argument("--email",    required=True, help="対象ユーザーのメールアドレス")
    parser.add_argument("--date",     required=True, metavar="YYYY-MM-DD", help="対象日")
    args = parser.parse_args()

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.key_file

    print(f"\n=== SUMTIME 単日明細チェック ===")
    print(f"  対象: {args.email} / {args.date}\n")

    sec = load_sumtime_secret(args.project)

    # 当日の working_achievements を1行ずつ取得
    sql_detail = """
        SELECT wa.id,
               wa.start_at,
               wa.end_at,
               wa.achievement_time,
               wa.working_memo,
               wc.name AS category_name
        FROM sumtime.working_achievements wa
        JOIN sumtime.users u ON wa.working_user_id = u.id
        LEFT JOIN sumtime.working_categories wc ON wa.working_category_id = wc.id
        WHERE u.email = %s
          AND DATE(wa.start_at) = %s
        ORDER BY wa.start_at
    """
    # working_category_id が無いスキーマ向けのフォールバック（カテゴリ無し）
    sql_detail_nocat = """
        SELECT wa.id,
               wa.start_at,
               wa.end_at,
               wa.achievement_time,
               wa.working_memo,
               NULL AS category_name
        FROM sumtime.working_achievements wa
        JOIN sumtime.users u ON wa.working_user_id = u.id
        WHERE u.email = %s
          AND DATE(wa.start_at) = %s
        ORDER BY wa.start_at
    """

    with SSHTunnelForwarder(
        (sec["ssh_host"], 22),
        ssh_username=sec["ssh_user"],
        ssh_password=sec["ssh_password"],
        remote_bind_address=("localhost", 5432),
    ) as tunnel:
        conn = psycopg2.connect(
            host="localhost",
            port=tunnel.local_bind_port,
            dbname=sec["db_name"],
            user=sec["db_user"],
            password=sec["db_password"],
        )
        cur = conn.cursor()
        try:
            cur.execute(sql_detail, (args.email, args.date))
        except Exception:
            conn.rollback()
            cur.execute(sql_detail_nocat, (args.email, args.date))
        rows = cur.fetchall()
        cur.close()
        conn.close()

    if not rows:
        print("  該当レコードがありません")
        return

    print(f"  {'ID':>8}  {'開始':<19} {'終了':<19} {'時間':>6}  {'カテゴリ':<16} メモ")
    print("  " + "-" * 90)
    total = 0.0
    for r in rows:
        rec_id, start_at, end_at, ach, memo, cat = r
        ach_f = float(ach) if ach is not None else 0.0
        total += ach_f
        print(f"  {rec_id:>8}  {str(start_at):<19} {str(end_at):<19} "
              f"{ach_f:>5.2f}h  {str(cat or '-'):<16} {memo or ''}")

    print("  " + "-" * 90)
    h = int(total)
    m = round((total - h) * 60)
    print(f"  レコード数: {len(rows)}件")
    print(f"  合計: {total:.2f}h （{h}時間{m:02d}分）  ← 突き合わせシステムが集計する値")


if __name__ == "__main__":
    main()

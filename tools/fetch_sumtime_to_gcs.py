"""
社内PC用 SUMTIMEデータ取得 → Cloud Storageアップロード スクリプト

処理フロー:
1. Secret Manager から SUMTIME接続情報を取得
2. SSHトンネル経由でSUMTIME DBに接続
3. 過去2週間の工数データを取得
4. JSON形式でCloud Storageにアップロード
5. Cloud FunctionsをHTTPで呼び出し（将来実装）

使い方:
  python fetch_sumtime_to_gcs.py \
    --key-file path/to/office-pc-key.json \
    --bucket kintai-kosu-sumtime-data \
    --project kintai-kosu-notification

事前準備:
  pip install google-cloud-secret-manager google-cloud-storage
      paramiko sshtunnel psycopg2-binary
"""

import argparse
import json
import sys
import os
from datetime import date, timedelta, datetime

# ライブラリ存在確認
missing = []
try:
    from google.cloud import secretmanager
except ImportError:
    missing.append("google-cloud-secret-manager")
try:
    from google.cloud import storage
except ImportError:
    missing.append("google-cloud-storage")
try:
    import paramiko
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    missing.append("paramiko sshtunnel")
try:
    import psycopg2
except ImportError:
    missing.append("psycopg2-binary")

if missing:
    print("[エラー] 以下のライブラリが未インストールです:")
    for m in missing:
        print(f"  pip install {m}")
    sys.exit(1)


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


# ─────────────────────────────────────────────
# Step 1: Secret Manager から接続情報を取得
# ─────────────────────────────────────────────
def get_secret(client: secretmanager.SecretManagerServiceClient,
               project_id: str, secret_name: str) -> str:
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def load_secrets(project_id: str) -> dict:
    print("\n[Step 1] Secret Manager から接続情報を取得...")
    client = secretmanager.SecretManagerServiceClient()
    secrets = {}
    secret_names = [
        "sumtime-ssh-host",
        "sumtime-ssh-user",
        "sumtime-ssh-password",
        "sumtime-db-host",
        "sumtime-db-name",
        "sumtime-db-user",
        "sumtime-db-password",
    ]
    for name in secret_names:
        secrets[name] = get_secret(client, project_id, name)
        print(f"[Step 1]   {name}: 取得済み")
    print("[Step 1] ✓ 全シークレット取得完了")
    return secrets


# ─────────────────────────────────────────────
# Step 2: SUMTIME DBからデータ取得
# ─────────────────────────────────────────────
def fetch_sumtime_data(secrets: dict, period_start: date, period_end: date) -> list:
    print(f"\n[Step 2] SUMTIME DBからデータ取得...")
    print(f"[Step 2]   対象期間: {period_start} 〜 {period_end}")

    ssh_host = secrets["sumtime-ssh-host"]
    ssh_user = secrets["sumtime-ssh-user"]
    ssh_pass = secrets["sumtime-ssh-password"]
    db_name  = secrets["sumtime-db-name"]
    db_user  = secrets["sumtime-db-user"]
    db_pass  = secrets["sumtime-db-password"]

    query = """
        SELECT
            u.email,
            u.name,
            DATE(wa.start_at) AS work_date,
            SUM(wa.achievement_time) * 60 AS total_minutes
        FROM sumtime.working_achievements wa
        JOIN sumtime.users u ON wa.working_user_id = u.id
        WHERE u.is_using = true
          AND DATE(wa.start_at) BETWEEN %s AND %s
        GROUP BY u.email, u.name, DATE(wa.start_at)
        ORDER BY u.email, work_date
    """

    with SSHTunnelForwarder(
        (ssh_host, 22),
        ssh_username=ssh_user,
        ssh_password=ssh_pass,
        remote_bind_address=("localhost", 5432),
    ) as tunnel:
        print(f"[Step 2]   SSHトンネル確立: {ssh_host} → localhost:{tunnel.local_bind_port}")

        conn = psycopg2.connect(
            host="localhost",
            port=tunnel.local_bind_port,
            dbname=db_name,
            user=db_user,
            password=db_pass,
        )
        cursor = conn.cursor()
        cursor.execute(query, (period_start.isoformat(), period_end.isoformat()))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

    records = [
        {
            "email":         row[0],
            "name":          row[1],
            "work_date":     row[2].isoformat(),
            "total_minutes": float(row[3]) if row[3] else 0.0,
        }
        for row in rows
    ]

    print(f"[Step 2] ✓ {len(records)} 件取得完了")
    return records


# ─────────────────────────────────────────────
# Step 3: Cloud Storage にアップロード
# ─────────────────────────────────────────────
def upload_to_gcs(bucket_name: str, records: list,
                  period_start: date, period_end: date) -> str:
    print(f"\n[Step 3] Cloud Storage にアップロード...")

    today = date.today().isoformat()
    blob_name = f"sumtime_data/{today}/sumtime_{today}.json"

    payload = {
        "fetched_at":    datetime.now().isoformat(),
        "period_start":  period_start.isoformat(),
        "period_end":    period_end.isoformat(),
        "record_count":  len(records),
        "records":       records,
    }

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(blob_name)
    blob.upload_from_string(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json"
    )

    gcs_path = f"gs://{bucket_name}/{blob_name}"
    print(f"[Step 3] ✓ アップロード完了: {gcs_path}")
    print(f"[Step 3]   レコード数: {len(records)} 件")
    return gcs_path


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="SUMTIMEデータ取得 → Cloud Storageアップロード"
    )
    parser.add_argument("--key-file", required=True,
                        help="GCPサービスアカウントキーファイルのパス")
    parser.add_argument("--bucket",   required=True,
                        help="Cloud Storageバケット名")
    parser.add_argument("--project",  required=True,
                        help="GCPプロジェクトID")
    args = parser.parse_args()

    # サービスアカウントキーを環境変数に設定
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.key_file

    print_section("SUMTIME データ取得 → Cloud Storage アップロード")

    # 対象期間: 実行日前日〜14日前
    today        = date.today()
    period_end   = today - timedelta(days=1)
    period_start = today - timedelta(days=14)
    print(f"  実行日:   {today}")
    print(f"  対象期間: {period_start} 〜 {period_end}")

    try:
        # Step 1: シークレット取得
        secrets = load_secrets(args.project)

        # Step 2: SUMTIMEデータ取得
        records = fetch_sumtime_data(secrets, period_start, period_end)

        # Step 3: Cloud Storageアップロード
        gcs_path = upload_to_gcs(args.bucket, records, period_start, period_end)

    except Exception as e:
        print(f"\n[エラー] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    print_section("完了")
    print(f"  SUMTIMEデータを正常にアップロードしました")
    print(f"  保存先: {gcs_path}")
    print(f"\n  次のステップ: Cloud Functionsを呼び出して突き合わせを実行")


if __name__ == "__main__":
    main()

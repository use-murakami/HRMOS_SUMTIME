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
import calendar
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

    # sumtime-credentials は JSON 形式で1件に統合されている
    secret_name = "sumtime-credentials"
    raw = get_secret(client, project_id, secret_name)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"シークレット '{secret_name}' がJSON形式ではありません: {e}"
        ) from e

    # 後方互換: 旧キー名の平坦なdictに展開して返す
    secrets = {
        "sumtime-ssh-host":     data["ssh_host"],
        "sumtime-ssh-user":     data["ssh_user"],
        "sumtime-ssh-password": data["ssh_password"],
        "sumtime-db-host":      data["db_host"],
        "sumtime-db-name":      data["db_name"],
        "sumtime-db-user":      data["db_user"],
        "sumtime-db-password":  data["db_password"],
    }
    print(f"[Step 1]   {secret_name}: 取得済み（7フィールド展開）")
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


# 全履歴を蓄積するマスターファイル（Cloud Functions はこれを最優先で読む）
MASTER_BLOB_NAME = "sumtime_data/master.json"


# ─────────────────────────────────────────────
# Step 3: Cloud Storage にアップロード
# ─────────────────────────────────────────────
def upload_to_gcs(bucket_name: str, records: list,
                  period_start: date, period_end: date) -> str:
    """
    取得したレコードを Cloud Storage に保存する。

      ① 日付別スナップショット（監査用。この実行で何を取得したかの記録）
      ② マスターファイルへマージ（email×日付キーで蓄積。CFはこれを読む）

    マージにより過去分が消えないため、過去月をいつでも参照可能になる。
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # ── ① 日付別スナップショット（監査用） ──────────────
    print(f"\n[Step 3] Cloud Storage にアップロード...")
    today = date.today().isoformat()
    snapshot_name = (
        f"sumtime_data/snapshots/{today}/"
        f"sumtime_{period_start.isoformat()}_{period_end.isoformat()}.json"
    )
    snapshot_payload = {
        "fetched_at":    datetime.now().isoformat(),
        "period_start":  period_start.isoformat(),
        "period_end":    period_end.isoformat(),
        "record_count":  len(records),
        "records":       records,
    }
    bucket.blob(snapshot_name).upload_from_string(
        json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    print(f"[Step 3]   ① スナップショット保存: gs://{bucket_name}/{snapshot_name}")
    print(f"[Step 3]      取得レコード数: {len(records)} 件")

    # ── ② マスターファイルへマージ ───────────────────────
    master_path = _merge_into_master(bucket, bucket_name, records)
    print(f"[Step 3] ✓ アップロード完了")
    return master_path


def _merge_into_master(bucket, bucket_name: str, new_records: list) -> str:
    """
    新規レコードをマスターファイル（全履歴）へマージする。

    キーは (email, work_date)。同一キーは新しい取得結果で上書きする
    （SUMTIME側でデータが修正された場合に最新値を反映するため）。
    """
    master_blob = bucket.blob(MASTER_BLOB_NAME)

    # 既存マスターを読み込み（なければ空から開始）
    merged: dict[tuple[str, str], dict] = {}
    if master_blob.exists():
        existing = json.loads(master_blob.download_as_text(encoding="utf-8"))
        for rec in existing.get("records", []):
            merged[(rec["email"], rec["work_date"])] = rec
        print(f"[Step 3]   ② 既存マスター: {len(merged)} 件を読み込み")
    else:
        print(f"[Step 3]   ② マスター新規作成")

    # 新規レコードで上書きマージ
    added, updated = 0, 0
    for rec in new_records:
        key = (rec["email"], rec["work_date"])
        if key in merged:
            updated += 1
        else:
            added += 1
        merged[key] = rec

    # email→work_date 順にソートして書き出し
    records = sorted(merged.values(), key=lambda r: (r["email"], r["work_date"]))
    work_dates = [r["work_date"] for r in records]
    payload = {
        "fetched_at":    datetime.now().isoformat(),
        "period_start":  min(work_dates) if work_dates else "",
        "period_end":    max(work_dates) if work_dates else "",
        "record_count":  len(records),
        "records":       records,
    }
    master_blob.upload_from_string(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    print(f"[Step 3]   ② マスター更新: 新規{added}件 / 更新{updated}件 "
          f"→ 合計{len(records)}件")
    if work_dates:
        print(f"[Step 3]      マスター期間: {min(work_dates)} 〜 {max(work_dates)}")
    return f"gs://{bucket_name}/{MASTER_BLOB_NAME}"


# ─────────────────────────────────────────────
# 対象期間の算出
# ─────────────────────────────────────────────
def resolve_period(args) -> tuple[date, date]:
    """
    コマンドライン引数から対象期間（開始日・終了日）を算出する。

    優先順位:
      1. --month YYYY-MM            … 指定月の1日〜末日
      2. --period-start / --period-end … 任意期間（両方指定が必須）
      3. （いずれも未指定）           … 従来動作: 実行日前日から遡って14日間

    Raises:
        ValueError: 引数の組み合わせ・形式が不正な場合
    """
    has_month  = args.month is not None
    has_range  = args.period_start is not None or args.period_end is not None

    if has_month and has_range:
        raise ValueError("--month と --period-start/--period-end は同時に指定できません")

    # ① 月指定
    if has_month:
        if not _is_valid_ym(args.month):
            raise ValueError(f"--month は YYYY-MM 形式で指定してください: {args.month!r}")
        year, month = map(int, args.month.split("-"))
        period_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        period_end = date(year, month, last_day)
        return period_start, period_end

    # ② 任意期間
    if has_range:
        if args.period_start is None or args.period_end is None:
            raise ValueError("--period-start と --period-end は両方指定してください")
        try:
            period_start = date.fromisoformat(args.period_start)
            period_end   = date.fromisoformat(args.period_end)
        except ValueError:
            raise ValueError("--period-start / --period-end は YYYY-MM-DD 形式で指定してください")
        if period_start > period_end:
            raise ValueError("--period-start は --period-end 以前の日付を指定してください")
        return period_start, period_end

    # ③ 従来動作: 実行日前日から遡って14日間
    today = date.today()
    period_end   = today - timedelta(days=1)
    period_start = today - timedelta(days=14)
    return period_start, period_end


def _is_valid_ym(value: str) -> bool:
    import re
    return bool(re.match(r"^\d{4}-\d{2}$", str(value)))


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
    # 対象期間オプション（未指定時は従来の14日動作）
    parser.add_argument("--month", default=None, metavar="YYYY-MM",
                        help="対象月を指定（例: 2026-03）。指定月の1日〜末日を取得")
    parser.add_argument("--period-start", default=None, metavar="YYYY-MM-DD",
                        help="任意期間の開始日（--period-end とセットで指定）")
    parser.add_argument("--period-end", default=None, metavar="YYYY-MM-DD",
                        help="任意期間の終了日（--period-start とセットで指定）")
    args = parser.parse_args()

    # サービスアカウントキーを環境変数に設定
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.key_file

    print_section("SUMTIME データ取得 → Cloud Storage アップロード")

    # 対象期間を算出
    try:
        period_start, period_end = resolve_period(args)
    except ValueError as e:
        print(f"\n[エラー] {e}", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    is_spot = (args.month is not None) or (args.period_start is not None)
    print(f"  実行日:   {today}")
    print(f"  対象期間: {period_start} 〜 {period_end}"
          + ("  ★スポット取得" if is_spot else ""))
    if is_spot:
        print(f"  ※ スポット取得です。確認後は通常の14日取得を再実行して")
        print(f"     現行データに戻してください（Cloud Functionsは最新ファイルを読みます）")

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

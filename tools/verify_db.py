"""
SUMTIME工数管理DB 接続確認スクリプト

確認項目:
1. SSHトンネル経由でPostgreSQLに接続できるか
2. テーブル一覧
3. 工数データのサンプルレコード（カラム名・型・値）

使い方:
  python verify_db.py \
    --ssh-host SSH_HOST \
    --ssh-port 22 \
    --ssh-user SSH_USER \
    --ssh-key-path ~/.ssh/id_rsa \
    --db-host DB_HOST \
    --db-port 5432 \
    --db-name DB_NAME \
    --db-user DB_USER \
    --db-password DB_PASSWORD

  ※ SSH認証は鍵認証(--ssh-key-path)またはパスワード認証(--ssh-password)のいずれかを指定
"""

import argparse
import json
import os
import sys
from datetime import datetime, date, time as dt_time
from decimal import Decimal

try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    print("[エラー] sshtunnel が未インストールです。以下を実行してください:")
    print("  python -m pip install sshtunnel")
    sys.exit(1)

try:
    import psycopg2
except ImportError:
    print("[エラー] psycopg2 が未インストールです。以下を実行してください:")
    print("  python -m pip install psycopg2-binary")
    sys.exit(1)


def json_serializer(obj):
    """JSON非対応の型を変換"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dt_time):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def save_json(filepath: str, data: dict):
    """JSONファイルに保存"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=json_serializer)
    print(f"  → 保存: {filepath}")


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def get_tables(cur):
    """テーブル一覧を取得・表示"""
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name
    """)
    rows = cur.fetchall()
    print(f"  テーブル数: {len(rows)}")
    for schema, name in rows:
        print(f"    {schema}.{name}")
    return rows


def get_columns(cur, schema: str, table: str):
    """指定テーブルのカラム情報を取得・表示"""
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, table))
    rows = cur.fetchall()
    print(f"\n  [{schema}.{table}] カラム一覧 ({len(rows)}列):")
    print(f"  {'カラム名':<30} {'型':<20} {'NULL可':<8} {'デフォルト'}")
    print(f"  {'-'*30} {'-'*20} {'-'*8} {'-'*20}")
    result = []
    for col_name, data_type, nullable, default in rows:
        default_str = str(default)[:20] if default else ""
        print(f"  {col_name:<30} {data_type:<20} {nullable:<8} {default_str}")
        result.append({
            "column_name": col_name,
            "data_type": data_type,
            "is_nullable": nullable,
            "column_default": default,
        })
    return result


def get_sample(cur, schema: str, table: str, limit: int = 5):
    """指定テーブルのサンプルデータを取得・表示"""
    cur.execute(f'SELECT * FROM "{schema}"."{table}" LIMIT %s', (limit,))
    rows = cur.fetchall()
    col_names = [desc[0] for desc in cur.description]

    print(f"\n  [{schema}.{table}] サンプルデータ (先頭{limit}件):")
    if not rows:
        print("    データなし")
        return []

    result = []
    for i, row in enumerate(rows):
        print(f"\n  --- レコード {i + 1} ---")
        record = {}
        for col, val in zip(col_names, row):
            print(f"    {col}: {val!r}")
            record[col] = val
        result.append(record)
    return result


def get_row_counts(cur, tables):
    """各テーブルの行数を取得・表示"""
    print(f"\n  テーブル別レコード数:")
    result = {}
    for schema, name in tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{name}"')
            count = cur.fetchone()[0]
            print(f"    {schema}.{name}: {count:,}件")
            result[f"{schema}.{name}"] = count
        except Exception as e:
            print(f"    {schema}.{name}: [エラー] {e}")
            result[f"{schema}.{name}"] = f"エラー: {e}"
            cur.connection.rollback()
    return result


def main():
    parser = argparse.ArgumentParser(description="SUMTIME工数管理DB 接続確認")

    # SSH接続情報
    parser.add_argument("--ssh-host", required=True, help="SSHサーバーのホスト名/IP")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSHポート (デフォルト: 22)")
    parser.add_argument("--ssh-user", required=True, help="SSHユーザー名")
    parser.add_argument("--ssh-key-path", default=None, help="SSH秘密鍵のパス (鍵認証の場合)")
    parser.add_argument("--ssh-password", default=None, help="SSHパスワード (パスワード認証の場合)")

    # DB接続情報
    parser.add_argument("--db-host", default="localhost", help="DBホスト (トンネル先、デフォルト: localhost)")
    parser.add_argument("--db-port", type=int, default=5432, help="DBポート (デフォルト: 5432)")
    parser.add_argument("--db-name", required=True, help="データベース名")
    parser.add_argument("--db-user", required=True, help="DBユーザー名")
    parser.add_argument("--db-password", required=True, help="DBパスワード")

    # オプション
    parser.add_argument("--table", default=None, help="詳細表示するテーブル名 (schema.table形式)")
    parser.add_argument("--limit", type=int, default=5, help="サンプル取得件数 (デフォルト: 5)")
    parser.add_argument("--output-dir", default=None, help="結果をファイル出力するディレクトリ (指定しない場合はコンソールのみ)")

    args = parser.parse_args()

    # SSH認証方式の確認
    ssh_kwargs = {}
    if args.ssh_key_path:
        ssh_kwargs["ssh_pkey"] = args.ssh_key_path
        auth_method = f"鍵認証 ({args.ssh_key_path})"
    elif args.ssh_password:
        ssh_kwargs["ssh_password"] = args.ssh_password
        auth_method = "パスワード認証"
    else:
        print("[エラー] --ssh-key-path または --ssh-password のいずれかを指定してください")
        sys.exit(1)

    try:
        # 1. SSHトンネル接続
        print_section("1. SSHトンネル接続")
        print(f"  接続先: {args.ssh_user}@{args.ssh_host}:{args.ssh_port}")
        print(f"  認証方式: {auth_method}")
        print(f"  トンネル先: {args.db_host}:{args.db_port}")

        with SSHTunnelForwarder(
            (args.ssh_host, args.ssh_port),
            ssh_username=args.ssh_user,
            remote_bind_address=(args.db_host, args.db_port),
            **ssh_kwargs,
        ) as tunnel:
            print(f"  SSHトンネル確立: localhost:{tunnel.local_bind_port} → {args.db_host}:{args.db_port}")

            # 2. PostgreSQL接続
            print_section("2. PostgreSQL接続")
            print(f"  データベース: {args.db_name}")
            print(f"  ユーザー: {args.db_user}")

            conn = psycopg2.connect(
                host="localhost",
                port=tunnel.local_bind_port,
                dbname=args.db_name,
                user=args.db_user,
                password=args.db_password,
            )
            cur = conn.cursor()

            # バージョン確認
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            print(f"  接続成功！ PostgreSQL バージョン: {version}")

            # 結果格納用
            output_data = {}

            # 3. テーブル一覧
            print_section("3. テーブル一覧")
            tables = get_tables(cur)
            output_data["tables"] = [f"{s}.{n}" for s, n in tables]

            # 4. テーブル別レコード数
            print_section("4. テーブル別レコード数")
            row_counts = get_row_counts(cur, tables)
            output_data["row_counts"] = row_counts

            # 5. テーブル詳細（カラム情報 + サンプルデータ）
            output_data["table_details"] = {}

            if args.table:
                parts = args.table.split(".")
                if len(parts) == 2:
                    schema, table = parts
                else:
                    schema, table = "public", parts[0]
                target_tables = [(schema, table)]
            else:
                target_tables = tables

            print_section("5. テーブル詳細")
            for schema, name in target_tables:
                columns = get_columns(cur, schema, name)
                sample = get_sample(cur, schema, name, args.limit)
                output_data["table_details"][f"{schema}.{name}"] = {
                    "columns": columns,
                    "sample_data": sample,
                }

            cur.close()
            conn.close()

            # ファイル出力
            if args.output_dir:
                out_dir = args.output_dir
                os.makedirs(out_dir, exist_ok=True)

                # 1. テーブル一覧 + レコード数
                save_json(
                    os.path.join(out_dir, "01_tables.json"),
                    {"tables": output_data["tables"], "row_counts": output_data["row_counts"]},
                )

                # 2. テーブルごとにカラム情報 + サンプルデータ
                for full_name, detail in output_data["table_details"].items():
                    safe_name = full_name.replace(".", "_")
                    save_json(
                        os.path.join(out_dir, f"02_{safe_name}.json"),
                        {
                            "table": full_name,
                            "columns": detail["columns"],
                            "sample_data": detail["sample_data"],
                        },
                    )

                # 3. 全体まとめ
                save_json(os.path.join(out_dir, "00_summary.json"), output_data)

                print(f"\n  出力先ディレクトリ: {os.path.abspath(out_dir)}")

            print(f"\n{'='*60}")
            print("  接続確認完了")
            print(f"{'='*60}")

    except Exception as e:
        print(f"\n[エラー] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

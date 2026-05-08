"""
Cloud Storage クライアント（SUMTIMEデータ読み込み）

Cloud Storage に保存された SUMTIME 工数データ（JSON）を読み込み、
突き合わせロジックで使いやすい形式に変換する。

データ構造（fetch_sumtime_to_gcs.py が生成するJSON）:
  {
    "fetched_at":    "2026-05-08T08:30:00",
    "period_start":  "2026-04-24",
    "period_end":    "2026-05-07",
    "record_count":  42,
    "records": [
      { "email": "yamada@use-eng.co.jp", "name": "山田太郎",
        "work_date": "2026-04-24", "total_minutes": 480.0 },
      ...
    ]
  }

ブロブ名前形式: sumtime_data/{YYYY-MM-DD}/sumtime_{YYYY-MM-DD}.json
"""
import json
from datetime import date
from typing import Optional

from google.cloud import storage
from google.api_core.exceptions import NotFound

from utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# 例外クラス
# ─────────────────────────────────────────────

class SumtimeDataNotFoundError(Exception):
    """SUMTIMEデータがCloud Storageに存在しない場合に発生する例外"""
    pass


# ─────────────────────────────────────────────
# パブリック関数
# ─────────────────────────────────────────────

def load_sumtime_data(bucket_name: str, blob_name: Optional[str] = None) -> dict:
    """
    Cloud StorageからSUMTIMEデータを読み込む。

    Args:
        bucket_name: Cloud Storageバケット名
        blob_name:   読み込むブロブ名。省略時は最新のブロブを自動検索する。

    Returns:
        {
          "fetched_at":   str,         # 取得日時（ISO形式）
          "period_start": str,         # 対象期間開始日（YYYY-MM-DD）
          "period_end":   str,         # 対象期間終了日（YYYY-MM-DD）
          "record_count": int,
          "records": [
            { "email": str, "name": str,
              "work_date": str, "total_minutes": float },
            ...
          ]
        }

    Raises:
        SumtimeDataNotFoundError: ブロブが存在しない場合
    """
    gcs_client = storage.Client()
    bucket = gcs_client.bucket(bucket_name)

    if blob_name is None:
        blob_name = _find_latest_blob_name(bucket)

    blob = bucket.blob(blob_name)
    try:
        content = blob.download_as_text(encoding="utf-8")
    except NotFound:
        raise SumtimeDataNotFoundError(
            f"SUMTIMEデータが見つかりません: gs://{bucket_name}/{blob_name}"
        )

    data = json.loads(content)
    logger.info(
        f"Loaded SUMTIME data: gs://{bucket_name}/{blob_name} "
        f"({data.get('record_count', '?')} records)"
    )
    return data


def parse_sumtime_records(records: list) -> dict:
    """
    SUMTIMEレコードリストを突き合わせ用の辞書形式に変換する。

    Args:
        records: load_sumtime_data() が返す "records" リスト

    Returns:
        { email: { "YYYY-MM-DD": total_minutes_int, ... }, ... }

    Example:
        [{"email": "a@x.jp", "work_date": "2026-04-24", "total_minutes": 480.0}]
        → {"a@x.jp": {"2026-04-24": 480}}
    """
    result: dict = {}
    for rec in records:
        email = rec["email"]
        work_date = rec["work_date"]
        minutes = int(float(rec.get("total_minutes", 0)))

        if email not in result:
            result[email] = {}
        result[email][work_date] = minutes

    return result


def build_today_blob_name(target_date: Optional[date] = None) -> str:
    """
    指定日（省略時は当日）のブロブ名を返す。

    Example:
        date(2026, 5, 8) → "sumtime_data/2026-05-08/sumtime_2026-05-08.json"
    """
    d = target_date or date.today()
    d_str = d.isoformat()
    return f"sumtime_data/{d_str}/sumtime_{d_str}.json"


# ─────────────────────────────────────────────
# プライベート関数
# ─────────────────────────────────────────────

def _find_latest_blob_name(bucket) -> str:
    """
    バケット内の sumtime_data/ プレフィックスを持つブロブのうち
    最新（名前の辞書順で最後）のものを返す。

    Raises:
        SumtimeDataNotFoundError: 該当するブロブが存在しない場合
    """
    blobs = list(bucket.list_blobs(prefix="sumtime_data/"))
    blobs = [b for b in blobs if b.name.endswith(".json")]

    if not blobs:
        raise SumtimeDataNotFoundError(
            "SUMTIMEデータが見つかりません: sumtime_data/ 配下にJSONファイルがありません"
        )

    # ブロブ名はパスに日付が含まれるため辞書順 = 日付順
    latest = sorted(blobs, key=lambda b: b.name)[-1]
    logger.info(f"Auto-detected latest SUMTIME blob: {latest.name}")
    return latest.name

"""
modules/storage_client.py の単体テスト
"""
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, call

from modules.storage_client import (
    load_sumtime_data,
    parse_sumtime_records,
    build_today_blob_name,
    SumtimeDataNotFoundError,
)


# ─────────────────────────────────────────────
# テスト用フィクスチャ
# ─────────────────────────────────────────────

SAMPLE_PAYLOAD = {
    "fetched_at":   "2026-05-08T08:30:00",
    "period_start": "2026-04-24",
    "period_end":   "2026-05-07",
    "record_count": 3,
    "records": [
        {"email": "yamada@use-eng.co.jp", "name": "山田太郎",
         "work_date": "2026-04-24", "total_minutes": 480.0},
        {"email": "yamada@use-eng.co.jp", "name": "山田太郎",
         "work_date": "2026-04-25", "total_minutes": 300.0},
        {"email": "sato@use-eng.co.jp",   "name": "佐藤花子",
         "work_date": "2026-04-24", "total_minutes": 450.0},
    ],
}


# ─────────────────────────────────────────────
# load_sumtime_data
# ─────────────────────────────────────────────

class TestLoadSumtimeData:
    """load_sumtime_data 関数のテスト"""

    @patch("modules.storage_client.storage.Client")
    def test_load_with_explicit_blob_name(self, mock_client_class):
        """明示的なブロブ名で正常にデータを読み込めること"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_blob = MagicMock()
        mock_blob.download_as_text.return_value = json.dumps(SAMPLE_PAYLOAD)
        mock_client.bucket.return_value.blob.return_value = mock_blob

        result = load_sumtime_data("my-bucket", "sumtime_data/2026-05-08/sumtime_2026-05-08.json")

        assert result["record_count"] == 3
        assert len(result["records"]) == 3
        mock_client.bucket.assert_called_once_with("my-bucket")
        mock_client.bucket.return_value.blob.assert_called_once_with(
            "sumtime_data/2026-05-08/sumtime_2026-05-08.json"
        )

    @patch("modules.storage_client.storage.Client")
    def test_blob_not_found_raises_error(self, mock_client_class):
        """ブロブが存在しない場合に SumtimeDataNotFoundError が発生すること"""
        from google.api_core.exceptions import NotFound
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_blob = MagicMock()
        mock_blob.download_as_text.side_effect = NotFound("not found")
        mock_client.bucket.return_value.blob.return_value = mock_blob

        with pytest.raises(SumtimeDataNotFoundError):
            load_sumtime_data("my-bucket", "nonexistent.json")

    @patch("modules.storage_client._find_latest_blob_name")
    @patch("modules.storage_client.storage.Client")
    def test_auto_detect_latest_blob(self, mock_client_class, mock_find_latest):
        """blob_name 省略時に最新ブロブを自動検索すること"""
        mock_find_latest.return_value = "sumtime_data/2026-05-08/sumtime_2026-05-08.json"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_blob = MagicMock()
        mock_blob.download_as_text.return_value = json.dumps(SAMPLE_PAYLOAD)
        mock_client.bucket.return_value.blob.return_value = mock_blob

        result = load_sumtime_data("my-bucket")

        mock_find_latest.assert_called_once()
        assert result["record_count"] == 3


# ─────────────────────────────────────────────
# parse_sumtime_records
# ─────────────────────────────────────────────

class TestParseSumtimeRecords:
    """parse_sumtime_records 関数のテスト"""

    def test_basic_conversion(self):
        """レコードリストを email → {date → minutes} 形式に変換できること"""
        records = SAMPLE_PAYLOAD["records"]
        result = parse_sumtime_records(records)

        assert "yamada@use-eng.co.jp" in result
        assert "sato@use-eng.co.jp" in result
        assert result["yamada@use-eng.co.jp"]["2026-04-24"] == 480
        assert result["yamada@use-eng.co.jp"]["2026-04-25"] == 300
        assert result["sato@use-eng.co.jp"]["2026-04-24"] == 450

    def test_total_minutes_is_int(self):
        """total_minutes が int に変換されること"""
        records = [
            {"email": "a@use-eng.co.jp", "name": "A",
             "work_date": "2026-04-24", "total_minutes": 480.5},
        ]
        result = parse_sumtime_records(records)
        assert isinstance(result["a@use-eng.co.jp"]["2026-04-24"], int)

    def test_empty_records(self):
        """空のレコードリストは空辞書を返すこと"""
        result = parse_sumtime_records([])
        assert result == {}

    def test_multiple_dates_per_user(self):
        """同一ユーザーの複数日が正しく格納されること"""
        records = [
            {"email": "x@use-eng.co.jp", "name": "X",
             "work_date": "2026-04-01", "total_minutes": 240.0},
            {"email": "x@use-eng.co.jp", "name": "X",
             "work_date": "2026-04-02", "total_minutes": 360.0},
        ]
        result = parse_sumtime_records(records)
        assert len(result["x@use-eng.co.jp"]) == 2
        assert result["x@use-eng.co.jp"]["2026-04-01"] == 240
        assert result["x@use-eng.co.jp"]["2026-04-02"] == 360


# ─────────────────────────────────────────────
# build_today_blob_name
# ─────────────────────────────────────────────

class TestBuildTodayBlobName:
    """build_today_blob_name 関数のテスト"""

    def test_with_explicit_date(self):
        """指定日のブロブ名が正しく生成されること"""
        result = build_today_blob_name(date(2026, 5, 8))
        assert result == "sumtime_data/2026-05-08/sumtime_2026-05-08.json"

    def test_format(self):
        """ブロブ名が期待するプレフィックスで始まること"""
        result = build_today_blob_name(date(2026, 1, 1))
        assert result.startswith("sumtime_data/")
        assert result.endswith(".json")


# ─────────────────────────────────────────────
# _find_latest_blob_name (内部関数: 間接テスト)
# ─────────────────────────────────────────────

class TestFindLatestBlob:
    """_find_latest_blob_name の動作確認（load_sumtime_data 経由）"""

    @patch("modules.storage_client.storage.Client")
    def test_no_blobs_raises_error(self, mock_client_class):
        """ブロブが1件もない場合に SumtimeDataNotFoundError が発生すること"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = []
        mock_client.bucket.return_value = mock_bucket

        with pytest.raises(SumtimeDataNotFoundError):
            load_sumtime_data("empty-bucket")

    @patch("modules.storage_client.storage.Client")
    def test_latest_blob_selected(self, mock_client_class):
        """複数ブロブがある場合に最新のものが選択されること"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # 3つのブロブを用意（ソート後の最後が選ばれること）
        def make_blob(name):
            b = MagicMock()
            b.name = name
            return b

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [
            make_blob("sumtime_data/2026-05-06/sumtime_2026-05-06.json"),
            make_blob("sumtime_data/2026-05-08/sumtime_2026-05-08.json"),
            make_blob("sumtime_data/2026-05-07/sumtime_2026-05-07.json"),
        ]
        mock_client.bucket.return_value = mock_bucket

        mock_blob = MagicMock()
        mock_blob.download_as_text.return_value = json.dumps(SAMPLE_PAYLOAD)
        mock_bucket.blob.return_value = mock_blob

        load_sumtime_data("my-bucket")

        # 最新日（2026-05-08）のブロブが選択されていること
        mock_bucket.blob.assert_called_once_with(
            "sumtime_data/2026-05-08/sumtime_2026-05-08.json"
        )

"""
utils/firestore_client.py の単体テスト
"""
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from utils.firestore_client import (
    load_settings,
    load_excluded_emails,
    save_execution_result,
    COLLECTION_SETTINGS,
    DOCUMENT_CONFIG,
    COLLECTION_EXCLUDED_EMPLOYEES,
    COLLECTION_EXECUTION_RESULTS,
)


# ─────────────────────────────────────────────
# フィクスチャ
# ─────────────────────────────────────────────

def make_db(doc_data=None, doc_exists=True, stream_docs=None):
    """Firestore クライアントのモックを生成する"""
    db = MagicMock()

    # document().get() のモック
    doc = MagicMock()
    doc.exists = doc_exists
    doc.to_dict.return_value = doc_data or {}
    db.collection.return_value.document.return_value.get.return_value = doc

    # stream() のモック
    stream_docs = stream_docs or []
    db.collection.return_value.stream.return_value = iter(stream_docs)

    return db


# ─────────────────────────────────────────────
# load_settings
# ─────────────────────────────────────────────

class TestLoadSettings:
    """load_settings のテスト"""

    def test_returns_defaults_when_doc_not_exists(self):
        """ドキュメントが存在しない場合にデフォルト値が返ること"""
        db = make_db(doc_exists=False)
        result = load_settings(db)
        assert result["threshold_minutes"] == 15
        assert result["period_days"] == 14

    def test_returns_stored_values(self):
        """Firestore に保存された値が返ること"""
        db = make_db(doc_data={"threshold_minutes": 30, "period_days": 7})
        result = load_settings(db)
        assert result["threshold_minutes"] == 30
        assert result["period_days"] == 7

    def test_partial_data_uses_defaults(self):
        """一部のフィールドが欠損している場合にデフォルト値が補完されること"""
        db = make_db(doc_data={"threshold_minutes": 30})
        result = load_settings(db)
        assert result["threshold_minutes"] == 30
        assert result["period_days"] == 14

    def test_accesses_correct_collection_and_document(self):
        """正しいコレクション・ドキュメントにアクセスすること"""
        db = make_db(doc_exists=False)
        load_settings(db)
        db.collection.assert_called_with(COLLECTION_SETTINGS)
        db.collection.return_value.document.assert_called_with(DOCUMENT_CONFIG)

    def test_values_are_int(self):
        """戻り値が int 型であること"""
        db = make_db(doc_data={"threshold_minutes": "20", "period_days": "10"})
        result = load_settings(db)
        assert isinstance(result["threshold_minutes"], int)
        assert isinstance(result["period_days"], int)


# ─────────────────────────────────────────────
# load_excluded_emails
# ─────────────────────────────────────────────

class TestLoadExcludedEmails:
    """load_excluded_emails のテスト"""

    def test_returns_empty_set_when_no_docs(self):
        """除外社員がいない場合に空 set が返ること"""
        db = make_db(stream_docs=[])
        result = load_excluded_emails(db)
        assert result == set()

    def test_returns_email_ids(self):
        """除外社員のメールアドレスが set で返ること"""
        doc1 = MagicMock()
        doc1.id = "yamada@use-eng.co.jp"
        doc2 = MagicMock()
        doc2.id = "sato@use-eng.co.jp"
        db = make_db(stream_docs=[doc1, doc2])

        result = load_excluded_emails(db)

        assert result == {"yamada@use-eng.co.jp", "sato@use-eng.co.jp"}

    def test_accesses_correct_collection(self):
        """正しいコレクションにアクセスすること"""
        db = make_db(stream_docs=[])
        load_excluded_emails(db)
        db.collection.assert_called_with(COLLECTION_EXCLUDED_EMPLOYEES)


# ─────────────────────────────────────────────
# save_execution_result
# ─────────────────────────────────────────────

class TestSaveExecutionResult:
    """save_execution_result のテスト"""

    def _call(self, db, **kwargs):
        defaults = {
            "executed_at":        datetime(2026, 5, 8, 9, 0),
            "period_start":       date(2026, 4, 24),
            "period_end":         date(2026, 5, 7),
            "mode":               "production",
            "is_preview":         False,
            "total_employees":    10,
            "notified_count":     3,
            "notified_employees": [],
            "errors":             [],
        }
        defaults.update(kwargs)
        return save_execution_result(db=db, **defaults)

    def test_returns_doc_id(self):
        """ドキュメントIDが返ること"""
        db = make_db()
        doc_id = self._call(db)
        assert doc_id == "20260508-0900"

    def test_doc_id_format(self):
        """ドキュメントIDが YYYYMMDD-HHmm 形式であること"""
        db = make_db()
        doc_id = self._call(db, executed_at=datetime(2026, 12, 31, 23, 59))
        assert doc_id == "20261231-2359"

    def test_set_called_with_correct_collection(self):
        """正しいコレクション・ドキュメントに set が呼ばれること"""
        db = MagicMock()
        self._call(db)
        db.collection.assert_called_with(COLLECTION_EXECUTION_RESULTS)

    def test_saved_data_contains_period(self):
        """保存データに period_start / period_end が含まれること"""
        db = MagicMock()
        self._call(db)
        saved = db.collection.return_value.document.return_value.set.call_args[0][0]
        assert saved["period_start"] == "2026-04-24"
        assert saved["period_end"]   == "2026-05-07"

    def test_saved_data_contains_counts(self):
        """保存データに total_employees / notified_count が含まれること"""
        db = MagicMock()
        self._call(db, total_employees=15, notified_count=5)
        saved = db.collection.return_value.document.return_value.set.call_args[0][0]
        assert saved["total_employees"] == 15
        assert saved["notified_count"]  == 5

    def test_saved_data_mode(self):
        """保存データに mode が含まれること"""
        db = MagicMock()
        self._call(db, mode="test")
        saved = db.collection.return_value.document.return_value.set.call_args[0][0]
        assert saved["mode"] == "test"

    def test_saved_data_is_preview(self):
        """保存データに is_preview が含まれること"""
        db = MagicMock()
        self._call(db, is_preview=True)
        saved = db.collection.return_value.document.return_value.set.call_args[0][0]
        assert saved["is_preview"] is True

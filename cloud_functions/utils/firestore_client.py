"""
Firestore ユーティリティ

管理UIとCloud Functionsが共有するFirestoreへのアクセスを提供する。

コレクション構成（仕様書 Section 10.5）:
  settings/config         — 突き合わせ設定（閾値・対象期間）
  excluded_employees/{email} — 通知除外社員
  execution_results/{id}  — 実行結果ログ
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────
# コレクション・ドキュメント名
# ─────────────────────────────────────────────
COLLECTION_SETTINGS           = "settings"
DOCUMENT_CONFIG               = "config"
COLLECTION_EXCLUDED_EMPLOYEES = "excluded_employees"
COLLECTION_EXECUTION_RESULTS  = "execution_results"


# ─────────────────────────────────────────────
# 設定の読み込み
# ─────────────────────────────────────────────

def load_settings(db: firestore.Client) -> dict:
    """
    Firestore から設定を読み込む。
    ドキュメントが存在しない場合はデフォルト値を返す。

    Returns:
        {
            "threshold_minutes": int,   # デフォルト: 15
            "period_days":       int,   # デフォルト: 14
        }
    """
    doc = db.collection(COLLECTION_SETTINGS).document(DOCUMENT_CONFIG).get()

    if not doc.exists:
        logger.info("Firestore settings not found. Using defaults.")
        return {"threshold_minutes": 15, "period_days": 14}

    data = doc.to_dict()
    settings = {
        "threshold_minutes": int(data.get("threshold_minutes", 15)),
        "period_days":       int(data.get("period_days", 14)),
    }
    logger.info(f"Firestore settings loaded: {settings}")
    return settings


# ─────────────────────────────────────────────
# 除外社員の読み込み
# ─────────────────────────────────────────────

def load_excluded_emails(db: firestore.Client) -> set:
    """
    Firestore から除外社員のメールアドレス一覧を取得する。

    Returns:
        除外社員のメールアドレスの set
    """
    docs = db.collection(COLLECTION_EXCLUDED_EMPLOYEES).stream()
    excluded = {doc.id for doc in docs}
    if excluded:
        logger.info(f"Excluded employees loaded: {excluded}")
    return excluded


# ─────────────────────────────────────────────
# 実行結果の書き込み
# ─────────────────────────────────────────────

def save_execution_result(
    db: firestore.Client,
    executed_at: datetime,
    period_start,
    period_end,
    mode: str,
    is_preview: bool,
    total_employees: int,
    notified_count: int,
    notified_employees: list,
    errors: list,
) -> str:
    """
    実行結果を Firestore に保存する。

    Args:
        db:                  Firestore クライアント
        executed_at:         実行日時
        period_start:        対象期間開始日（date）
        period_end:          対象期間終了日（date）
        mode:                "production" or "test"
        is_preview:          プレビュー実行か否か
        total_employees:     突き合わせ対象の全社員数
        notified_count:      通知済み社員数
        notified_employees:  通知対象者リスト（list of dict）
        errors:              エラーメッセージリスト

    Returns:
        ドキュメントID（YYYYMMDD-HHmm形式）
    """
    doc_id = executed_at.strftime("%Y%m%d-%H%M")

    data = {
        "executed_at":        executed_at,
        "period_start":       period_start.isoformat(),
        "period_end":         period_end.isoformat(),
        "mode":               mode,
        "is_preview":         is_preview,
        "total_employees":    total_employees,
        "notified_count":     notified_count,
        "notified_employees": notified_employees,
        "errors":             errors,
    }

    db.collection(COLLECTION_EXECUTION_RESULTS).document(doc_id).set(data)
    logger.info(f"Execution result saved: {doc_id} (notified={notified_count})")
    return doc_id

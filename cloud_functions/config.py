"""
設定管理モジュール

環境変数またはデフォルト値から設定を読み込む。
Cloud Functions デプロイ時に環境変数で設定値を上書き可能。
"""
import os

# ─────────────────────────────────────────────
# GCP設定
# ─────────────────────────────────────────────
GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "kintai-kosu-notification")
GCS_BUCKET_NAME: str = os.environ.get("GCS_BUCKET_NAME", "kintai-kosu-sumtime-data")

# ─────────────────────────────────────────────
# 突き合わせ設定
# ─────────────────────────────────────────────
# 差異の閾値（分）: この値以上の差異がある日を通知対象とする
THRESHOLD_MINUTES: int = int(os.environ.get("THRESHOLD_MINUTES", "15"))

# デフォルトの遡り日数: period_days パラメータ未指定時に使用
DEFAULT_PERIOD_DAYS: int = int(os.environ.get("DEFAULT_PERIOD_DAYS", "14"))

# 突き合わせ対象の勤務区分（カンマ区切り環境変数で上書き可能）
_segments_env: str = os.environ.get("TARGET_WORK_SEGMENTS", "")
TARGET_WORK_SEGMENTS: list = (
    _segments_env.split(",") if _segments_env
    else ["出勤", "出勤（休出）", "出勤（午前休）", "出勤（午後休）"]
)

# ─────────────────────────────────────────────
# メール設定
# ─────────────────────────────────────────────
# 送信元メールアドレス（共有メールボックス）
SENDER_EMAIL: str = os.environ.get("SENDER_EMAIL", "kintai-notice@use-eng.co.jp")

# 管理者メールアドレス（サマリー・エラー通知先）
ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "y-murakami@use-eng.co.jp")

# メール送信間隔（秒）: Graph API レート制限対策
EMAIL_SEND_INTERVAL_SEC: float = float(os.environ.get("EMAIL_SEND_INTERVAL_SEC", "0.5"))

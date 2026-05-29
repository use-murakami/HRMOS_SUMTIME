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

# ─────────────────────────────────────────────
# 安全ガード設定
# ─────────────────────────────────────────────
# メール送信先の強制上書き（開発・テスト中の誤送信防止）
# 設定されている間は、個人通知メールを含む全メールをこのアドレスに転送する
# 本番移行時は環境変数を空文字列（""）に設定して解除する
#
# ⚠️ デフォルトで管理者アドレスを設定しているため、
#    環境変数 OVERRIDE_EMAIL_TO="" を明示的に指定しない限り
#    社員へのメール送信は行われない（フェイルセーフ設計）
OVERRIDE_EMAIL_TO: str = os.environ.get("OVERRIDE_EMAIL_TO", "y-murakami@use-eng.co.jp")

# テストモードフラグ（管理UIの通知設定変更をロック）
# True（デフォルト）: 管理者以外の通知設定をUIから変更不可にする
# False: 全社員の通知設定を自由に変更可能（本番移行後に環境変数で解除）
#
# ⚠️ OVERRIDE_EMAIL_TO と組み合わせることで二重の安全ガードを実現:
#    - TESTING_MODE=True : UIから誤って通知ONにできない
#    - OVERRIDE_EMAIL_TO 設定済み : 万一ONになっても管理者宛に転送
TESTING_MODE: bool = os.environ.get("TESTING_MODE", "true").lower() not in ("false", "0", "")

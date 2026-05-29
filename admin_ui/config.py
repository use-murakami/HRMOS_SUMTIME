"""
管理UI 設定モジュール
"""
import os

# GCP設定
GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "kintai-kosu-notification")

# Cloud Functions URL（デプロイ後に環境変数で設定）
CLOUD_FUNCTION_URL: str = os.environ.get("CLOUD_FUNCTION_URL", "")

# 管理者メールアドレス（通知設定ガードに使用）
ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "y-murakami@use-eng.co.jp")

# Basic認証ユーザー名
ADMIN_UI_USER: str = os.environ.get("ADMIN_UI_USER", "admin")

# テストモードフラグ（通知設定変更のロック）
TESTING_MODE: bool = os.environ.get("TESTING_MODE", "true").lower() not in ("false", "0", "")

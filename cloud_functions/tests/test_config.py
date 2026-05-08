"""
config.py の単体テスト
"""
import importlib
import pytest


class TestDefaultValues:
    """デフォルト値のテスト"""

    def test_threshold_minutes_default(self):
        """デフォルト閾値が15分であること"""
        import config
        importlib.reload(config)
        assert config.THRESHOLD_MINUTES == 15

    def test_default_period_days(self):
        """デフォルト遡り日数が14日であること"""
        import config
        importlib.reload(config)
        assert config.DEFAULT_PERIOD_DAYS == 14

    def test_target_work_segments_count(self):
        """デフォルト勤務区分が4種類であること"""
        import config
        importlib.reload(config)
        assert len(config.TARGET_WORK_SEGMENTS) == 4

    def test_target_work_segments_values(self):
        """デフォルト勤務区分の内容確認"""
        import config
        importlib.reload(config)
        assert "出勤" in config.TARGET_WORK_SEGMENTS
        assert "出勤（休出）" in config.TARGET_WORK_SEGMENTS
        assert "出勤（午前休）" in config.TARGET_WORK_SEGMENTS
        assert "出勤（午後休）" in config.TARGET_WORK_SEGMENTS

    def test_sender_email_default(self):
        """デフォルト送信元メールアドレスの確認"""
        import config
        importlib.reload(config)
        assert config.SENDER_EMAIL == "kintai-notice@use-eng.co.jp"

    def test_admin_email_default(self):
        """管理者メールアドレスの確認"""
        import config
        importlib.reload(config)
        assert config.ADMIN_EMAIL == "y-murakami@use-eng.co.jp"

    def test_gcp_project_id_default(self):
        """デフォルトGCPプロジェクトIDの確認"""
        import config
        importlib.reload(config)
        assert config.GCP_PROJECT_ID == "kintai-kosu-notification"

    def test_gcs_bucket_name_default(self):
        """デフォルトCloud StorageバケットIDの確認"""
        import config
        importlib.reload(config)
        assert config.GCS_BUCKET_NAME == "kintai-kosu-sumtime-data"


class TestEnvOverride:
    """環境変数による上書きのテスト"""

    def test_threshold_from_env(self, monkeypatch):
        """環境変数でTHRESHOLD_MINUTESを上書きできること"""
        monkeypatch.setenv("THRESHOLD_MINUTES", "30")
        import config
        importlib.reload(config)
        assert config.THRESHOLD_MINUTES == 30

    def test_period_days_from_env(self, monkeypatch):
        """環境変数でDEFAULT_PERIOD_DAYSを上書きできること"""
        monkeypatch.setenv("DEFAULT_PERIOD_DAYS", "7")
        import config
        importlib.reload(config)
        assert config.DEFAULT_PERIOD_DAYS == 7

    def test_work_segments_from_env(self, monkeypatch):
        """環境変数でTARGET_WORK_SEGMENTSを上書きできること"""
        monkeypatch.setenv("TARGET_WORK_SEGMENTS", "出勤,出勤（休出）")
        import config
        importlib.reload(config)
        assert config.TARGET_WORK_SEGMENTS == ["出勤", "出勤（休出）"]

    def test_sender_email_from_env(self, monkeypatch):
        """環境変数でSENDER_EMAILを上書きできること"""
        monkeypatch.setenv("SENDER_EMAIL", "test@example.com")
        import config
        importlib.reload(config)
        assert config.SENDER_EMAIL == "test@example.com"

"""
utils/secret_manager.py の単体テスト
"""
from unittest.mock import MagicMock, patch, call
import pytest
from utils.secret_manager import get_secret, load_all_secrets


class TestGetSecret:
    """get_secret 関数のテスト"""

    @patch("utils.secret_manager.secretmanager.SecretManagerServiceClient")
    def test_get_secret_success(self, mock_client_class):
        """正常にシークレットを取得できること"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = "test-secret-value"
        mock_client.access_secret_version.return_value = mock_response

        result = get_secret("my-project", "my-secret")

        assert result == "test-secret-value"
        mock_client.access_secret_version.assert_called_once_with(
            request={"name": "projects/my-project/secrets/my-secret/versions/latest"}
        )

    @patch("utils.secret_manager.secretmanager.SecretManagerServiceClient")
    def test_get_secret_not_found(self, mock_client_class):
        """シークレットが存在しない場合に例外が発生すること"""
        from google.api_core.exceptions import NotFound
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.access_secret_version.side_effect = NotFound("not found")

        with pytest.raises(NotFound):
            get_secret("my-project", "nonexistent-secret")

    @patch("utils.secret_manager.secretmanager.SecretManagerServiceClient")
    def test_get_secret_permission_denied(self, mock_client_class):
        """アクセス権限がない場合に例外が発生すること"""
        from google.api_core.exceptions import PermissionDenied
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.access_secret_version.side_effect = PermissionDenied("denied")

        with pytest.raises(PermissionDenied):
            get_secret("my-project", "my-secret")


class TestLoadAllSecrets:
    """load_all_secrets 関数のテスト"""

    @patch("utils.secret_manager.get_secret")
    def test_load_all_secrets_count(self, mock_get_secret):
        """11件のシークレットが取得されること"""
        mock_get_secret.return_value = "dummy-value"

        result = load_all_secrets("my-project")

        assert len(result) == 11

    @patch("utils.secret_manager.get_secret")
    def test_load_all_secrets_keys(self, mock_get_secret):
        """必要なシークレットキーが全て含まれること"""
        mock_get_secret.return_value = "dummy-value"

        result = load_all_secrets("my-project")

        expected_keys = {
            "hrmos-secret-key",
            "sumtime-ssh-host", "sumtime-ssh-user", "sumtime-ssh-password",
            "sumtime-db-host", "sumtime-db-name",
            "sumtime-db-user", "sumtime-db-password",
            "azure-tenant-id", "azure-client-id", "azure-client-secret",
        }
        assert set(result.keys()) == expected_keys

    @patch("utils.secret_manager.get_secret")
    def test_load_all_secrets_project_id_passed(self, mock_get_secret):
        """プロジェクトIDが各シークレット取得に渡されること"""
        mock_get_secret.return_value = "dummy-value"

        load_all_secrets("kintai-kosu-notification")

        for c in mock_get_secret.call_args_list:
            assert c[0][0] == "kintai-kosu-notification"

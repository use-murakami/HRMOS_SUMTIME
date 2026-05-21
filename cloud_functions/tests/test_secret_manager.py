"""
utils/secret_manager.py の単体テスト
"""
import json
from unittest.mock import MagicMock, patch
import pytest
from utils.secret_manager import get_secret, _get_secret_json, load_all_secrets


# ─────────────────────────────────────────────
# テスト用フィクスチャ
# ─────────────────────────────────────────────

HRMOS_DATA = {"secret_key": "hrmos-val"}
SUMTIME_DATA = {
    "ssh_host": "ssh-h", "ssh_user": "ssh-u", "ssh_password": "ssh-p",
    "db_host": "db-h", "db_name": "db-n", "db_user": "db-u", "db_password": "db-p",
}
AZURE_DATA = {
    "tenant_id": "t-id", "client_id": "c-id", "client_secret": "c-sec",
}


def make_get_secret_json_side_effect():
    """_get_secret_json のモック用 side_effect を返す"""
    def side_effect(project_id, secret_name):
        return {
            "hrmos-credentials":   HRMOS_DATA,
            "sumtime-credentials": SUMTIME_DATA,
            "azure-credentials":   AZURE_DATA,
        }[secret_name]
    return side_effect


# ─────────────────────────────────────────────
# get_secret
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# _get_secret_json
# ─────────────────────────────────────────────

class TestGetSecretJson:
    """_get_secret_json 関数のテスト"""

    @patch("utils.secret_manager.get_secret")
    def test_valid_json_returns_dict(self, mock_get_secret):
        """正常なJSONシークレットを dict として取得できること"""
        mock_get_secret.return_value = '{"key": "value", "num": 42}'

        result = _get_secret_json("my-project", "my-secret")

        assert result == {"key": "value", "num": 42}

    @patch("utils.secret_manager.get_secret")
    def test_invalid_json_raises_value_error(self, mock_get_secret):
        """JSON形式でないシークレットの場合に ValueError が発生すること"""
        mock_get_secret.return_value = "plain-text-not-json"

        with pytest.raises(ValueError, match="JSON形式ではありません"):
            _get_secret_json("my-project", "my-secret")

    @patch("utils.secret_manager.get_secret")
    def test_project_id_passed_to_get_secret(self, mock_get_secret):
        """project_id と secret_name が get_secret に正しく渡されること"""
        mock_get_secret.return_value = '{"k": "v"}'

        _get_secret_json("test-project", "test-secret")

        mock_get_secret.assert_called_once_with("test-project", "test-secret")


# ─────────────────────────────────────────────
# load_all_secrets
# ─────────────────────────────────────────────

class TestLoadAllSecrets:
    """load_all_secrets 関数のテスト"""

    @patch("utils.secret_manager._get_secret_json")
    def test_load_all_secrets_count(self, mock_get_json):
        """11件のキーが返ること（後方互換）"""
        mock_get_json.side_effect = make_get_secret_json_side_effect()

        result = load_all_secrets("my-project")

        assert len(result) == 11

    @patch("utils.secret_manager._get_secret_json")
    def test_load_all_secrets_keys(self, mock_get_json):
        """必要なシークレットキーが全て含まれること"""
        mock_get_json.side_effect = make_get_secret_json_side_effect()

        result = load_all_secrets("my-project")

        expected_keys = {
            "hrmos-secret-key",
            "sumtime-ssh-host", "sumtime-ssh-user", "sumtime-ssh-password",
            "sumtime-db-host", "sumtime-db-name",
            "sumtime-db-user", "sumtime-db-password",
            "azure-tenant-id", "azure-client-id", "azure-client-secret",
        }
        assert set(result.keys()) == expected_keys

    @patch("utils.secret_manager._get_secret_json")
    def test_load_all_secrets_values_mapped_correctly(self, mock_get_json):
        """JSONの各フィールドが正しいキー名にマッピングされること"""
        mock_get_json.side_effect = make_get_secret_json_side_effect()

        result = load_all_secrets("my-project")

        assert result["hrmos-secret-key"] == "hrmos-val"
        assert result["sumtime-ssh-host"] == "ssh-h"
        assert result["sumtime-db-password"] == "db-p"
        assert result["azure-tenant-id"] == "t-id"
        assert result["azure-client-secret"] == "c-sec"

    @patch("utils.secret_manager._get_secret_json")
    def test_load_all_secrets_calls_3_secrets(self, mock_get_json):
        """GCPへのアクセスがちょうど3回（3グループ）であること"""
        mock_get_json.side_effect = make_get_secret_json_side_effect()

        load_all_secrets("my-project")

        assert mock_get_json.call_count == 3

    @patch("utils.secret_manager._get_secret_json")
    def test_load_all_secrets_project_id_passed(self, mock_get_json):
        """プロジェクトIDが全アクセスに渡されること"""
        mock_get_json.side_effect = make_get_secret_json_side_effect()

        load_all_secrets("kintai-kosu-notification")

        for c in mock_get_json.call_args_list:
            assert c[0][0] == "kintai-kosu-notification"

"""
Google Cloud Secret Manager ユーティリティ

Secret Manager からシークレット値を取得する。
"""
from google.cloud import secretmanager


def get_secret(project_id: str, secret_name: str) -> str:
    """
    Secret Manager から最新バージョンのシークレット値を取得する。

    Args:
        project_id: GCPプロジェクトID
        secret_name: シークレット名

    Returns:
        シークレットの値（文字列）

    Raises:
        google.api_core.exceptions.NotFound: シークレットが存在しない場合
        google.api_core.exceptions.PermissionDenied: アクセス権限がない場合
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def load_all_secrets(project_id: str) -> dict:
    """
    システムに必要な全シークレットを一括取得する。

    Args:
        project_id: GCPプロジェクトID

    Returns:
        シークレット名 → 値 の辞書
    """
    secret_names = [
        "hrmos-secret-key",
        "sumtime-ssh-host",
        "sumtime-ssh-user",
        "sumtime-ssh-password",
        "sumtime-db-host",
        "sumtime-db-name",
        "sumtime-db-user",
        "sumtime-db-password",
        "azure-tenant-id",
        "azure-client-id",
        "azure-client-secret",
    ]
    return {name: get_secret(project_id, name) for name in secret_names}

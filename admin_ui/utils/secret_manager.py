"""
Secret Manager ユーティリティ（管理UI用）
cloud_functions/utils/secret_manager.py から get_secret のみを再実装。
"""
from google.cloud import secretmanager


def get_secret(project_id: str, secret_name: str) -> str:
    """Secret Manager から最新バージョンのシークレット値を取得する。"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

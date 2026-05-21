"""
Google Cloud Secret Manager ユーティリティ

Secret Manager からシークレット値を取得する。

シークレット構成（3グループ・JSON形式）:
  hrmos-credentials:   {"secret_key": "..."}
  sumtime-credentials: {"ssh_host":"...","ssh_user":"...","ssh_password":"...",
                         "db_host":"...","db_name":"...","db_user":"...","db_password":"..."}
  azure-credentials:   {"tenant_id":"...","client_id":"...","client_secret":"..."}

GCP無料枠: アクティブなシークレットバージョン数 6以下
  3シークレット × 1バージョン = 3（無料枠内）
"""
import json

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


def _get_secret_json(project_id: str, secret_name: str) -> dict:
    """
    Secret Manager から JSON 形式のシークレットを取得して dict として返す。

    Args:
        project_id: GCPプロジェクトID
        secret_name: シークレット名（JSON形式であること）

    Returns:
        パース済み dict

    Raises:
        ValueError: シークレットの値が JSON 形式でない場合
        google.api_core.exceptions.NotFound: シークレットが存在しない場合
        google.api_core.exceptions.PermissionDenied: アクセス権限がない場合
    """
    raw = get_secret(project_id, secret_name)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"シークレット '{secret_name}' がJSON形式ではありません: {e}"
        ) from e


def load_all_secrets(project_id: str) -> dict:
    """
    システムに必要な全シークレットを一括取得する。

    GCPには3グループのJSON形式で保存されているが、
    戻り値は後方互換のため平坦なdict（旧11キー形式）で返す。

    Args:
        project_id: GCPプロジェクトID

    Returns:
        シークレット名 → 値 の辞書（11キー）:
        {
            "hrmos-secret-key":    "...",
            "sumtime-ssh-host":    "...",
            "sumtime-ssh-user":    "...",
            "sumtime-ssh-password":"...",
            "sumtime-db-host":     "...",
            "sumtime-db-name":     "...",
            "sumtime-db-user":     "...",
            "sumtime-db-password": "...",
            "azure-tenant-id":     "...",
            "azure-client-id":     "...",
            "azure-client-secret": "...",
        }

    Raises:
        ValueError: いずれかのシークレットがJSON形式でない場合
        google.api_core.exceptions.NotFound: シークレットが存在しない場合
    """
    hrmos   = _get_secret_json(project_id, "hrmos-credentials")
    sumtime = _get_secret_json(project_id, "sumtime-credentials")
    azure   = _get_secret_json(project_id, "azure-credentials")

    return {
        # hrmos-credentials
        "hrmos-secret-key":     hrmos["secret_key"],
        # sumtime-credentials
        "sumtime-ssh-host":     sumtime["ssh_host"],
        "sumtime-ssh-user":     sumtime["ssh_user"],
        "sumtime-ssh-password": sumtime["ssh_password"],
        "sumtime-db-host":      sumtime["db_host"],
        "sumtime-db-name":      sumtime["db_name"],
        "sumtime-db-user":      sumtime["db_user"],
        "sumtime-db-password":  sumtime["db_password"],
        # azure-credentials
        "azure-tenant-id":      azure["tenant_id"],
        "azure-client-id":      azure["client_id"],
        "azure-client-secret":  azure["client_secret"],
    }

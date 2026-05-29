"""
HRMOS API クライアント（管理UI用・ユーザー一覧取得のみ）
"""
import requests

HRMOS_BASE_URL = "https://ieyasu.co/api/use/v1"


def get_hrmos_users(secret_key: str) -> list[dict]:
    """
    HRMOS からユーザー一覧を取得して返す。

    Returns:
        [{"email": "...", "display_name": "...", "user_id": ...}, ...]
    """
    # トークン取得
    resp = requests.get(
        f"{HRMOS_BASE_URL}/authentication/token",
        headers={"Authorization": f"Basic {secret_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()["token"]

    # ユーザー一覧取得（ページネーション対応）
    users = []
    page = 1
    while True:
        resp = requests.get(
            f"{HRMOS_BASE_URL}/users",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        for u in data:
            email = u.get("email", "")
            if email:
                users.append({
                    "user_id":      u["id"],
                    "email":        email,
                    "display_name": f"{u.get('last_name', '')} {u.get('first_name', '')}".strip(),
                })
        if len(data) < 100:
            break
        page += 1

    return users

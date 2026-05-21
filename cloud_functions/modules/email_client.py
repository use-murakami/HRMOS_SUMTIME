"""
Microsoft Graph API メール送信クライアント

OAuth 2.0 Client Credentials Flow でアクセストークンを取得し、
Graph API (Mail.Send) でメールを送信する。

Graph API ドキュメント:
  POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
  POST https://graph.microsoft.com/v1.0/users/{sender}/sendMail

エラーハンドリング（仕様書 Section 7.2）:
  - 最大3回リトライ（指数バックオフ）
  - HTTP 429: Retry-After ヘッダーに従って待機
  - 連続送信間隔: 0.5秒
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from utils.logger import get_logger

logger = get_logger(__name__)

# Graph API エンドポイント
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
SEND_MAIL_URL_TEMPLATE = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

# リトライ設定
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 5          # 指数バックオフの基底値（秒）
SEND_INTERVAL_SECONDS = 0.5       # 連続送信間隔（秒）
DEFAULT_RETRY_AFTER_SECONDS = 5   # Retry-After ヘッダーが存在しない場合のデフォルト値


@dataclass
class EmailMessage:
    """送信するメールのデータクラス"""
    to_address: str
    subject: str
    body_html: str


class GraphApiError(Exception):
    """Graph API からのエラーレスポンス"""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class EmailClient:
    """
    Microsoft Graph API を使ったメール送信クライアント。

    Args:
        tenant_id:     Azure AD テナントID
        client_id:     アプリケーション（クライアント）ID
        client_secret: クライアントシークレット
        sender_email:  送信元メールアドレス（共有メールボックス）
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        sender_email: str,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._sender_email = sender_email
        self._access_token: str | None = None

    # ─────────────────────────────────────────────
    # トークン取得
    # ─────────────────────────────────────────────

    def get_access_token(self) -> str:
        """
        OAuth 2.0 Client Credentials Flow でアクセストークンを取得する。

        Returns:
            アクセストークン（文字列）

        Raises:
            GraphApiError: トークン取得に失敗した場合
        """
        url = TOKEN_URL_TEMPLATE.format(tenant_id=self._tenant_id)
        data = {
            "grant_type":    "client_credentials",
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
            "scope":         "https://graph.microsoft.com/.default",
        }

        logger.info("Acquiring Graph API access token...")
        response = requests.post(url, data=data, timeout=30)

        if response.status_code != 200:
            raise GraphApiError(
                response.status_code,
                f"トークン取得失敗: {response.text[:200]}",
            )

        token = response.json().get("access_token")
        if not token:
            raise GraphApiError(200, "レスポンスに access_token が含まれていません")

        logger.info("Access token acquired successfully")
        return token

    # ─────────────────────────────────────────────
    # メール送信（単体）
    # ─────────────────────────────────────────────

    def send_email(self, message: EmailMessage) -> None:
        """
        1件のメールを送信する。リトライ付き。

        Args:
            message: 送信するメールの内容

        Raises:
            GraphApiError: リトライ上限を超えてもメール送信に失敗した場合
        """
        if self._access_token is None:
            self._access_token = self.get_access_token()

        url = SEND_MAIL_URL_TEMPLATE.format(sender=self._sender_email)
        body = _build_send_mail_body(message)
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type":  "application/json",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.post(url, json=body, headers=headers, timeout=30)

                if response.status_code == 202:
                    # 成功（HTTP 202 Accepted）
                    logger.info(
                        f"Email sent to {message.to_address} "
                        f"(subject: {message.subject!r})"
                    )
                    return

                if response.status_code == 429:
                    # レート制限 → Retry-After に従って待機
                    retry_after = int(
                        response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS)
                    )
                    logger.warning(
                        f"Rate limited (429). Waiting {retry_after}s "
                        f"[attempt {attempt}/{MAX_RETRIES}]"
                    )
                    time.sleep(retry_after)
                    continue

                if response.status_code == 401:
                    # トークン期限切れ → 再取得してリトライ
                    logger.warning(
                        f"Access token expired (401). Re-acquiring... "
                        f"[attempt {attempt}/{MAX_RETRIES}]"
                    )
                    self._access_token = self.get_access_token()
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    continue

                # その他のエラー → 指数バックオフでリトライ
                backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"Send failed (HTTP {response.status_code}). "
                    f"Retrying in {backoff}s [attempt {attempt}/{MAX_RETRIES}]"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(backoff)

            except requests.Timeout:
                backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"Request timeout. Retrying in {backoff}s "
                    f"[attempt {attempt}/{MAX_RETRIES}]"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(backoff)

        raise GraphApiError(
            0,
            f"メール送信がリトライ上限({MAX_RETRIES}回)を超えて失敗しました: to={message.to_address}",
        )

    # ─────────────────────────────────────────────
    # 複数メール送信
    # ─────────────────────────────────────────────

    def send_emails(self, messages: list[EmailMessage]) -> list[str]:
        """
        複数件のメールを送信する。送信失敗したアドレスをリストで返す。

        連続送信間隔（SEND_INTERVAL_SECONDS）を空けて順番に送信する。
        1件失敗しても残りの送信を継続する。

        Args:
            messages: 送信するメールのリスト

        Returns:
            送信失敗した to_address のリスト（全成功時は空リスト）
        """
        failed = []

        for i, message in enumerate(messages):
            if i > 0:
                time.sleep(SEND_INTERVAL_SECONDS)

            try:
                self.send_email(message)
            except Exception as e:
                logger.error(
                    f"Failed to send email to {message.to_address}: {e}"
                )
                failed.append(message.to_address)

        if failed:
            logger.warning(f"Send failures: {failed}")
        else:
            logger.info(f"All {len(messages)} emails sent successfully")

        return failed


# ─────────────────────────────────────────────
# プライベート関数
# ─────────────────────────────────────────────

def _build_send_mail_body(message: EmailMessage) -> dict:
    """
    Graph API sendMail のリクエストボディを組み立てる。

    Args:
        message: メール内容

    Returns:
        dict（JSON シリアライズ可能）
    """
    return {
        "message": {
            "subject": message.subject,
            "body": {
                "contentType": "HTML",
                "content":     message.body_html,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": message.to_address,
                    }
                }
            ],
        },
        "saveToSentItems": False,
    }

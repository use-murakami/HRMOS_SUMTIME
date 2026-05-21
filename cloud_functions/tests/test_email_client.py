"""
modules/email_client.py の単体テスト
"""
import time
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from modules.email_client import (
    EmailClient,
    EmailMessage,
    GraphApiError,
    _build_send_mail_body,
    SEND_INTERVAL_SECONDS,
)


# ─────────────────────────────────────────────
# フィクスチャ
# ─────────────────────────────────────────────

@pytest.fixture
def client():
    return EmailClient(
        tenant_id="test-tenant",
        client_id="test-client",
        client_secret="test-secret",
        sender_email="kintai-notice@use-eng.co.jp",
    )


@pytest.fixture
def message():
    return EmailMessage(
        to_address="yamada@use-eng.co.jp",
        subject="テスト件名",
        body_html="<p>テスト本文</p>",
    )


def make_response(status_code: int, json_data: dict | None = None,
                  headers: dict | None = None, text: str = "") -> MagicMock:
    """requests.Response のモックを生成する"""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.headers = headers or {}
    r.text = text
    return r


# ─────────────────────────────────────────────
# _build_send_mail_body
# ─────────────────────────────────────────────

class TestBuildSendMailBody:
    """_build_send_mail_body の単体テスト"""

    def test_structure(self, message):
        """必要なキーを持つ dict が生成されること"""
        body = _build_send_mail_body(message)

        assert "message" in body
        assert body["message"]["subject"] == "テスト件名"
        assert body["message"]["body"]["contentType"] == "HTML"
        assert body["message"]["body"]["content"] == "<p>テスト本文</p>"
        assert body["message"]["toRecipients"][0]["emailAddress"]["address"] == "yamada@use-eng.co.jp"

    def test_save_to_sent_items_false(self, message):
        """saveToSentItems が False であること"""
        body = _build_send_mail_body(message)
        assert body["saveToSentItems"] is False


# ─────────────────────────────────────────────
# EmailClient.get_access_token
# ─────────────────────────────────────────────

class TestGetAccessToken:
    """get_access_token のテスト"""

    @patch("modules.email_client.requests.post")
    def test_success(self, mock_post, client):
        """HTTP 200 でトークンが返ること"""
        mock_post.return_value = make_response(200, json_data={"access_token": "tok123"})

        token = client.get_access_token()

        assert token == "tok123"

    @patch("modules.email_client.requests.post")
    def test_http_error_raises_graph_api_error(self, mock_post, client):
        """HTTP 400 で GraphApiError が発生すること"""
        mock_post.return_value = make_response(400, text="Bad Request")

        with pytest.raises(GraphApiError) as exc_info:
            client.get_access_token()
        assert "400" in str(exc_info.value)

    @patch("modules.email_client.requests.post")
    def test_missing_token_raises_graph_api_error(self, mock_post, client):
        """レスポンスに access_token がない場合に GraphApiError が発生すること"""
        mock_post.return_value = make_response(200, json_data={"error": "no_token"})

        with pytest.raises(GraphApiError, match="access_token"):
            client.get_access_token()

    @patch("modules.email_client.requests.post")
    def test_token_url_contains_tenant_id(self, mock_post, client):
        """トークン取得 URL にテナントIDが含まれること"""
        mock_post.return_value = make_response(200, json_data={"access_token": "tok"})

        client.get_access_token()

        call_url = mock_post.call_args[0][0]
        assert "test-tenant" in call_url

    @patch("modules.email_client.requests.post")
    def test_request_data_contains_credentials(self, mock_post, client):
        """リクエストデータに client_id / client_secret が含まれること"""
        mock_post.return_value = make_response(200, json_data={"access_token": "tok"})

        client.get_access_token()

        data = mock_post.call_args[1]["data"]
        assert data["client_id"] == "test-client"
        assert data["client_secret"] == "test-secret"
        assert data["grant_type"] == "client_credentials"


# ─────────────────────────────────────────────
# EmailClient.send_email
# ─────────────────────────────────────────────

class TestSendEmail:
    """send_email のテスト"""

    @patch("modules.email_client.requests.post")
    def test_send_success_202(self, mock_post, client, message):
        """HTTP 202 でメールが送信されること"""
        client._access_token = "existing-token"
        mock_post.return_value = make_response(202)

        client.send_email(message)  # 例外なし

        mock_post.assert_called_once()

    @patch("modules.email_client.requests.post")
    def test_send_url_contains_sender(self, mock_post, client, message):
        """送信 URL に送信元アドレスが含まれること"""
        client._access_token = "tok"
        mock_post.return_value = make_response(202)

        client.send_email(message)

        call_url = mock_post.call_args[0][0]
        assert "kintai-notice@use-eng.co.jp" in call_url

    @patch("modules.email_client.requests.post")
    def test_authorization_header_set(self, mock_post, client, message):
        """Authorization ヘッダーにトークンが設定されること"""
        client._access_token = "my-token"
        mock_post.return_value = make_response(202)

        client.send_email(message)

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-token"

    @patch("modules.email_client.requests.post")
    def test_token_acquired_if_none(self, mock_post, client, message):
        """_access_token が None の場合にトークン取得が実行されること"""
        # 1回目の呼び出し: トークン取得 → 2回目: メール送信
        mock_post.side_effect = [
            make_response(200, json_data={"access_token": "new-tok"}),
            make_response(202),
        ]

        client.send_email(message)

        assert mock_post.call_count == 2

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_retry_on_500(self, mock_post, mock_sleep, client, message):
        """HTTP 500 で最大3回リトライされること"""
        client._access_token = "tok"
        mock_post.return_value = make_response(500, text="Internal Server Error")

        with pytest.raises(GraphApiError):
            client.send_email(message)

        assert mock_post.call_count == 3

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_retry_on_429_uses_retry_after(self, mock_post, mock_sleep, client, message):
        """HTTP 429 で Retry-After ヘッダーの秒数だけ sleep されること"""
        client._access_token = "tok"
        mock_post.side_effect = [
            make_response(429, headers={"Retry-After": "10"}),
            make_response(202),
        ]

        client.send_email(message)

        mock_sleep.assert_called_with(10)

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_retry_on_401_reacquires_token(self, mock_post, mock_sleep, client, message):
        """HTTP 401 でトークンを再取得してリトライすること"""
        client._access_token = "expired-tok"
        mock_post.side_effect = [
            make_response(401),                                      # 1回目: 401
            make_response(200, json_data={"access_token": "new-tok"}),  # トークン再取得
            make_response(202),                                      # 2回目: 成功
        ]

        client.send_email(message)

        assert client._access_token == "new-tok"

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_retry_success_on_second_attempt(self, mock_post, mock_sleep, client, message):
        """1回失敗後、2回目で成功すること（GraphApiError を raise しない）"""
        client._access_token = "tok"
        mock_post.side_effect = [
            make_response(500),
            make_response(202),
        ]

        client.send_email(message)  # 例外なし

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_timeout_triggers_retry(self, mock_post, mock_sleep, client, message):
        """タイムアウトでリトライされること"""
        client._access_token = "tok"
        mock_post.side_effect = [
            requests.Timeout(),
            requests.Timeout(),
            requests.Timeout(),
        ]

        with pytest.raises(GraphApiError):
            client.send_email(message)

        assert mock_post.call_count == 3


# ─────────────────────────────────────────────
# EmailClient.send_emails
# ─────────────────────────────────────────────

class TestSendEmails:
    """send_emails のテスト"""

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_all_success_returns_empty_list(self, mock_post, mock_sleep, client):
        """全件送信成功時に空リストが返ること"""
        client._access_token = "tok"
        mock_post.return_value = make_response(202)
        messages = [
            EmailMessage("a@use-eng.co.jp", "件名A", "<p>A</p>"),
            EmailMessage("b@use-eng.co.jp", "件名B", "<p>B</p>"),
        ]

        failed = client.send_emails(messages)

        assert failed == []
        assert mock_post.call_count == 2

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_interval_sleep_between_sends(self, mock_post, mock_sleep, client):
        """2件目以降の送信前に SEND_INTERVAL_SECONDS の sleep があること"""
        client._access_token = "tok"
        mock_post.return_value = make_response(202)
        messages = [
            EmailMessage("a@use-eng.co.jp", "件名A", "<p>A</p>"),
            EmailMessage("b@use-eng.co.jp", "件名B", "<p>B</p>"),
            EmailMessage("c@use-eng.co.jp", "件名C", "<p>C</p>"),
        ]

        client.send_emails(messages)

        # 3件送信なので sleep は2回（件数 - 1）
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(SEND_INTERVAL_SECONDS)

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_failed_addresses_returned(self, mock_post, mock_sleep, client):
        """送信失敗したアドレスがリストに含まれること"""
        client._access_token = "tok"
        # a は成功、b は失敗、c は成功
        mock_post.side_effect = [
            make_response(202),
            make_response(500),
            make_response(500),
            make_response(500),
            make_response(202),
        ]
        messages = [
            EmailMessage("a@use-eng.co.jp", "件名A", "<p>A</p>"),
            EmailMessage("b@use-eng.co.jp", "件名B", "<p>B</p>"),
            EmailMessage("c@use-eng.co.jp", "件名C", "<p>C</p>"),
        ]

        failed = client.send_emails(messages)

        assert failed == ["b@use-eng.co.jp"]

    @patch("modules.email_client.time.sleep")
    @patch("modules.email_client.requests.post")
    def test_continue_after_failure(self, mock_post, mock_sleep, client):
        """1件失敗しても残りの送信が継続されること"""
        client._access_token = "tok"
        mock_post.side_effect = [
            make_response(500),  # a: 失敗 (3回リトライ)
            make_response(500),
            make_response(500),
            make_response(202),  # b: 成功
        ]
        messages = [
            EmailMessage("a@use-eng.co.jp", "件名A", "<p>A</p>"),
            EmailMessage("b@use-eng.co.jp", "件名B", "<p>B</p>"),
        ]

        failed = client.send_emails(messages)

        assert "a@use-eng.co.jp" in failed
        assert "b@use-eng.co.jp" not in failed

    @patch("modules.email_client.requests.post")
    def test_no_sleep_before_first_send(self, mock_post, client):
        """最初の送信前に sleep が呼ばれないこと"""
        client._access_token = "tok"
        mock_post.return_value = make_response(202)

        with patch("modules.email_client.time.sleep") as mock_sleep:
            client.send_emails([EmailMessage("a@use-eng.co.jp", "件名", "<p>本文</p>")])
            mock_sleep.assert_not_called()

    @patch("modules.email_client.requests.post")
    def test_empty_list_returns_empty(self, mock_post, client):
        """空リストを渡すと空リストが返ること"""
        result = client.send_emails([])
        assert result == []
        mock_post.assert_not_called()

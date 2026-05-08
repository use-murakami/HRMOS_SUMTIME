"""
modules/hrmos_client.py の単体テスト
"""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, call
from modules.hrmos_client import (
    HrmosClient, HrmosUser, HrmosWorkOutput,
    parse_hhmm, compute_months,
)


# ─────────────────────────────────────────────
# parse_hhmm
# ─────────────────────────────────────────────

class TestParseHhmm:
    """parse_hhmm 関数のテスト"""

    def test_standard(self):
        """通常の時間文字列を分に変換できること"""
        assert parse_hhmm("8:00") == 480

    def test_with_minutes(self):
        """分が含まれる場合も正しく変換できること"""
        assert parse_hhmm("1:30") == 90

    def test_zero(self):
        """ゼロ時間は0分になること"""
        assert parse_hhmm("0:00") == 0

    def test_none(self):
        """None は 0 を返すこと"""
        assert parse_hhmm(None) == 0

    def test_empty_string(self):
        """空文字は 0 を返すこと"""
        assert parse_hhmm("") == 0

    def test_half_hour(self):
        """30分の変換"""
        assert parse_hhmm("0:30") == 30

    def test_large_hours(self):
        """10時間以上の変換"""
        assert parse_hhmm("10:15") == 615


# ─────────────────────────────────────────────
# compute_months
# ─────────────────────────────────────────────

class TestComputeMonths:
    """compute_months 関数のテスト"""

    def test_single_month(self):
        """同一月の場合は1件返すこと"""
        result = compute_months(date(2026, 4, 1), date(2026, 4, 30))
        assert result == ["2026-04"]

    def test_two_months(self):
        """月をまたぐ場合は2件返すこと"""
        result = compute_months(date(2026, 3, 25), date(2026, 4, 7))
        assert result == ["2026-03", "2026-04"]

    def test_year_boundary(self):
        """年末年始をまたぐ場合も正しく処理されること"""
        result = compute_months(date(2025, 12, 20), date(2026, 1, 5))
        assert result == ["2025-12", "2026-01"]

    def test_same_day(self):
        """開始日と終了日が同じ場合は1件返すこと"""
        result = compute_months(date(2026, 5, 8), date(2026, 5, 8))
        assert result == ["2026-05"]


# ─────────────────────────────────────────────
# HrmosClient.get_token
# ─────────────────────────────────────────────

class TestGetToken:
    """HrmosClient.get_token のテスト"""

    @patch("modules.hrmos_client.requests.get")
    def test_get_token_success(self, mock_get):
        """トークンを正常に取得できること"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "test-token-123"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        client = HrmosClient("my-secret-key", base_url="https://example.com/v1")
        token = client.get_token()

        assert token == "test-token-123"
        mock_get.assert_called_once_with(
            "https://example.com/v1/authentication/token",
            headers={"Authorization": "Basic my-secret-key"},
            timeout=30,
        )

    @patch("modules.hrmos_client.requests.get")
    def test_get_token_http_error(self, mock_get):
        """HTTP エラー時に例外が発生すること"""
        import requests as req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("401 Unauthorized")
        mock_get.return_value = mock_resp

        client = HrmosClient("bad-key", base_url="https://example.com/v1")
        with pytest.raises(req.HTTPError):
            client.get_token()


# ─────────────────────────────────────────────
# HrmosClient.get_users
# ─────────────────────────────────────────────

class TestGetUsers:
    """HrmosClient.get_users のテスト"""

    def _make_user(self, n):
        return {
            "id": n,
            "email": f"user{n}@use-eng.co.jp",
            "last_name": f"姓{n}",
            "first_name": f"名{n}",
            "number": f"A{n:04d}",
        }

    @patch("modules.hrmos_client.requests.get")
    def test_single_page(self, mock_get):
        """1ページのみのユーザー一覧を取得できること"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [self._make_user(1), self._make_user(2)]
        mock_resp.headers = {"X-Total-Page": "1"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        client = HrmosClient("key", base_url="https://example.com/v1")
        users = client.get_users("token-abc")

        assert len(users) == 2
        assert users[0].email == "user1@use-eng.co.jp"
        assert users[0].display_name == "姓1 名1"
        assert users[1].employee_id == "A0002"

    @patch("modules.hrmos_client.time.sleep")
    @patch("modules.hrmos_client.requests.get")
    def test_pagination(self, mock_get, mock_sleep):
        """複数ページのユーザー一覧を全て取得できること"""
        resp_page1 = MagicMock()
        resp_page1.json.return_value = [self._make_user(i) for i in range(1, 4)]
        resp_page1.headers = {"X-Total-Page": "2"}
        resp_page1.raise_for_status.return_value = None

        resp_page2 = MagicMock()
        resp_page2.json.return_value = [self._make_user(4)]
        resp_page2.headers = {"X-Total-Page": "2"}
        resp_page2.raise_for_status.return_value = None

        mock_get.side_effect = [resp_page1, resp_page2]

        client = HrmosClient("key", base_url="https://example.com/v1")
        users = client.get_users("token-abc")

        assert len(users) == 4
        assert mock_sleep.called  # ページ間でスリープが呼ばれること


# ─────────────────────────────────────────────
# HrmosClient.get_work_outputs
# ─────────────────────────────────────────────

class TestGetWorkOutputs:
    """HrmosClient.get_work_outputs のテスト"""

    def _make_work_item(self, day: str, segment: str, working_hours: str):
        return {
            "number": "A0001",
            "user_id": 1,
            "day": day,
            "segment_display_title": segment,
            "actual_working_hours": working_hours,
            "start_at": "09:00",
            "end_at": "18:00",
            "total_break_time": "1:00",
        }

    @patch("modules.hrmos_client.requests.get")
    def test_filters_by_date(self, mock_get):
        """対象期間外のレコードが除外されること"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            self._make_work_item("2026-04-24", "出勤", "8:00"),   # 対象内
            self._make_work_item("2026-04-20", "出勤", "8:00"),   # 対象外（期間前）
            self._make_work_item("2026-05-08", "出勤", "8:00"),   # 対象外（期間後）
        ]
        mock_resp.headers = {"X-Total-Page": "1"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        client = HrmosClient("key", base_url="https://example.com/v1")
        outputs = client.get_work_outputs(
            "token",
            months=["2026-04"],
            period_start=date(2026, 4, 21),
            period_end=date(2026, 5, 7),
            target_segments=["出勤"],
        )

        assert len(outputs) == 1
        assert outputs[0].date == date(2026, 4, 24)

    @patch("modules.hrmos_client.requests.get")
    def test_filters_by_segment(self, mock_get):
        """対象外の勤務区分のレコードが除外されること"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            self._make_work_item("2026-04-24", "出勤", "8:00"),       # 対象
            self._make_work_item("2026-04-25", "公休", "0:00"),       # 除外
            self._make_work_item("2026-04-26", "出勤（休出）", "8:00"),  # 対象
        ]
        mock_resp.headers = {"X-Total-Page": "1"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        client = HrmosClient("key", base_url="https://example.com/v1")
        outputs = client.get_work_outputs(
            "token",
            months=["2026-04"],
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            target_segments=["出勤", "出勤（休出）"],
        )

        assert len(outputs) == 2
        segments = {o.segment for o in outputs}
        assert segments == {"出勤", "出勤（休出）"}

    @patch("modules.hrmos_client.requests.get")
    def test_working_minutes_converted(self, mock_get):
        """actual_working_hours が分に変換されること"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            self._make_work_item("2026-04-24", "出勤", "8:30"),
        ]
        mock_resp.headers = {"X-Total-Page": "1"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        client = HrmosClient("key", base_url="https://example.com/v1")
        outputs = client.get_work_outputs(
            "token",
            months=["2026-04"],
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            target_segments=["出勤"],
        )

        assert outputs[0].working_minutes == 510  # 8時間30分 = 510分

    @patch("modules.hrmos_client.time.sleep")
    @patch("modules.hrmos_client.requests.get")
    def test_rate_limit_retry(self, mock_get, mock_sleep):
        """429 レート制限時にリトライすること"""
        resp_429 = MagicMock()
        resp_429.status_code = 429

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = [self._make_work_item("2026-04-24", "出勤", "8:00")]
        resp_ok.headers = {"X-Total-Page": "1"}
        resp_ok.raise_for_status.return_value = None

        mock_get.side_effect = [resp_429, resp_ok]

        client = HrmosClient("key", base_url="https://example.com/v1")
        outputs = client.get_work_outputs(
            "token",
            months=["2026-04"],
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            target_segments=["出勤"],
        )

        assert len(outputs) == 1
        mock_sleep.assert_called()  # リトライ待機が呼ばれること

    @patch("modules.hrmos_client.time.sleep")
    @patch("modules.hrmos_client.requests.get")
    def test_rate_limit_exceeded(self, mock_get, mock_sleep):
        """リトライ上限を超えた場合に RuntimeError が発生すること"""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        mock_get.return_value = resp_429

        client = HrmosClient("key", base_url="https://example.com/v1")
        with pytest.raises(RuntimeError, match="rate limit exceeded"):
            client.get_work_outputs(
                "token",
                months=["2026-04"],
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                target_segments=["出勤"],
            )

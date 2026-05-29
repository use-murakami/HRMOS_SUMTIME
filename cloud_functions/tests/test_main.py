"""
main.py の単体テスト
"""
import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch, call

import flask
import pytest
from flask import Request
from werkzeug.test import EnvironBuilder

# テスト対象のインポート前に Flask アプリを初期化
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import _parse_params, _calc_period, _build_preview_response
from modules.reconciler import DayDiff, EmployeeDiff


# ─────────────────────────────────────────────
# Flask テストアプリ
# ─────────────────────────────────────────────

@pytest.fixture
def app():
    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    return app


def make_request(body: dict) -> Request:
    """JSON ボディを持つ Flask Request オブジェクトを生成する（コンテキスト不要）"""
    builder = EnvironBuilder(
        method="POST",
        content_type="application/json",
        data=json.dumps(body),
    )
    return Request(builder.get_environ())


# ─────────────────────────────────────────────
# _parse_params
# ─────────────────────────────────────────────

class TestParseParams:
    """_parse_params のテスト"""

    def test_production_mode(self):
        """production モードが正常に解析されること"""
        req = make_request({"mode": "production"})
        params = _parse_params(req)
        assert params["mode"] == "production"

    def test_test_mode_with_email(self):
        """test モードと target_email が正常に解析されること"""
        req = make_request({"mode": "test", "target_email": "a@use-eng.co.jp"})
        params = _parse_params(req)
        assert params["mode"] == "test"
        assert params["target_email"] == "a@use-eng.co.jp"

    def test_invalid_mode_raises(self):
        """不正な mode で ValueError が発生すること"""
        req = make_request({"mode": "invalid"})
        with pytest.raises(ValueError, match="mode"):
            _parse_params(req)

    def test_test_mode_without_email_raises(self):
        """test モードで target_email がない場合に ValueError が発生すること"""
        req = make_request({"mode": "test"})
        with pytest.raises(ValueError, match="target_email"):
            _parse_params(req)

    def test_period_days_parsed(self):
        """period_days が int として解析されること"""
        req = make_request({"mode": "production", "period_days": 7})
        params = _parse_params(req)
        assert params["period_days"] == 7

    def test_period_month_parsed(self):
        """period_month が文字列として解析されること"""
        req = make_request({"mode": "production", "period_month": "2026-04"})
        params = _parse_params(req)
        assert params["period_month"] == "2026-04"

    def test_both_period_raises(self):
        """period_days と period_month の同時指定で ValueError が発生すること"""
        req = make_request({
            "mode": "production",
            "period_days": 7,
            "period_month": "2026-04",
        })
        with pytest.raises(ValueError):
            _parse_params(req)

    def test_invalid_period_days_raises(self):
        """period_days に非正整数を指定した場合に ValueError が発生すること"""
        req = make_request({"mode": "production", "period_days": -1})
        with pytest.raises(ValueError, match="period_days"):
            _parse_params(req)

    def test_invalid_period_month_format_raises(self):
        """period_month のフォーマットが不正な場合に ValueError が発生すること"""
        req = make_request({"mode": "production", "period_month": "2026/04"})
        with pytest.raises(ValueError, match="period_month"):
            _parse_params(req)

    def test_preview_default_false(self):
        """preview のデフォルトが False であること"""
        req = make_request({"mode": "production"})
        params = _parse_params(req)
        assert params["preview"] is False

    def test_preview_true(self):
        """preview=true が解析されること"""
        req = make_request({"mode": "production", "preview": True})
        params = _parse_params(req)
        assert params["preview"] is True

    def test_empty_body_raises(self):
        """空ボディで ValueError が発生すること"""
        req = make_request({})
        with pytest.raises(ValueError):
            _parse_params(req)


# ─────────────────────────────────────────────
# _calc_period
# ─────────────────────────────────────────────

class TestCalcPeriod:
    """_calc_period のテスト"""

    @patch("main.date")
    def test_period_days(self, mock_date):
        """period_days 指定で正しい期間が算出されること"""
        mock_date.today.return_value = date(2026, 5, 8)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        start, end = _calc_period(period_days=7, period_month=None)

        assert end   == date(2026, 5, 7)   # today - 1
        assert start == date(2026, 5, 1)   # today - 7

    @patch("main.date")
    def test_period_days_14_default(self, mock_date):
        """period_days=14 で14日分の期間が算出されること"""
        mock_date.today.return_value = date(2026, 5, 8)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        start, end = _calc_period(period_days=14, period_month=None)

        assert end   == date(2026, 5, 7)
        assert start == date(2026, 4, 24)

    def test_period_month(self):
        """period_month 指定で月初〜月末が期間として設定されること"""
        start, end = _calc_period(period_days=None, period_month="2026-04")

        assert start == date(2026, 4, 1)
        assert end   == date(2026, 4, 30)

    def test_period_month_february_non_leap(self):
        """period_month で非閏年2月末が正しく算出されること"""
        start, end = _calc_period(period_days=None, period_month="2025-02")

        assert start == date(2025, 2, 1)
        assert end   == date(2025, 2, 28)

    def test_period_month_february_leap(self):
        """period_month で閏年2月末が正しく算出されること"""
        start, end = _calc_period(period_days=None, period_month="2024-02")

        assert start == date(2024, 2, 1)
        assert end   == date(2024, 2, 29)


# ─────────────────────────────────────────────
# _build_preview_response
# ─────────────────────────────────────────────

class TestBuildPreviewResponse:
    """_build_preview_response のテスト"""

    def make_emp(self):
        return EmployeeDiff(
            email="yamada@use-eng.co.jp",
            display_name="山田太郎",
            diff_days=[
                DayDiff(
                    date=date(2026, 4, 24),
                    hrmos_minutes=480,
                    sumtime_minutes=450,
                    diff_minutes=30,
                    is_sumtime_registered=True,
                )
            ],
            period_start=date(2026, 4, 24),
            period_end=date(2026, 5, 7),
        )

    def test_status_is_preview(self):
        """status が 'preview' であること"""
        result = _build_preview_response([], date(2026, 4, 24), date(2026, 5, 7), 10)
        assert result["status"] == "preview"

    def test_total_employees(self):
        """total_employees が正しく設定されること"""
        result = _build_preview_response([], date(2026, 4, 24), date(2026, 5, 7), 10)
        assert result["total_employees"] == 10

    def test_notified_count(self):
        """notified_count が差異のある社員数と一致すること"""
        emp = self.make_emp()
        result = _build_preview_response([emp], date(2026, 4, 24), date(2026, 5, 7), 10)
        assert result["notified_count"] == 1

    def test_diff_results_contains_email(self):
        """diff_results に email が含まれること"""
        emp = self.make_emp()
        result = _build_preview_response([emp], date(2026, 4, 24), date(2026, 5, 7), 10)
        assert result["diff_results"][0]["email"] == "yamada@use-eng.co.jp"

    def test_diff_days_count(self):
        """diff_days_count が正しいこと"""
        emp = self.make_emp()
        result = _build_preview_response([emp], date(2026, 4, 24), date(2026, 5, 7), 10)
        assert result["diff_results"][0]["diff_days_count"] == 1

    def test_diff_days_detail(self):
        """diff_days の各フィールドが正しいこと"""
        emp = self.make_emp()
        result = _build_preview_response([emp], date(2026, 4, 24), date(2026, 5, 7), 10)
        day = result["diff_results"][0]["diff_days"][0]
        assert day["date"]            == "2026-04-24"
        assert day["hrmos_minutes"]   == 480
        assert day["sumtime_minutes"] == 450
        assert day["diff_minutes"]    == 30
        assert day["is_anomaly"]      is False

    def test_empty_diff_results(self):
        """差異なしの場合に diff_results が空リストであること"""
        result = _build_preview_response([], date(2026, 4, 24), date(2026, 5, 7), 10)
        assert result["diff_results"] == []
        assert result["notified_count"] == 0

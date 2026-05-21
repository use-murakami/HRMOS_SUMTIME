"""
modules/email_builder.py の単体テスト
"""
from datetime import date, datetime

import pytest

from modules.email_builder import (
    build_personal_email,
    build_admin_summary_email,
    build_error_email,
    _format_date_jp,
    _format_period,
    _html_escape,
)
from modules.reconciler import DayDiff, EmployeeDiff


# ─────────────────────────────────────────────
# フィクスチャ
# ─────────────────────────────────────────────

def make_day_diff(
    work_date: date,
    hrmos_minutes: int | None,
    sumtime_minutes: int | None,
    diff_minutes: int,
    is_sumtime_registered: bool = True,
    is_anomaly: bool = False,
    anomaly_message: str = "",
) -> DayDiff:
    return DayDiff(
        date=work_date,
        hrmos_minutes=hrmos_minutes,
        sumtime_minutes=sumtime_minutes,
        diff_minutes=diff_minutes,
        is_sumtime_registered=is_sumtime_registered,
        is_anomaly=is_anomaly,
        anomaly_message=anomaly_message,
    )


def make_employee_diff(
    email: str = "yamada@use-eng.co.jp",
    display_name: str = "山田太郎",
    diff_days: list | None = None,
    period_start: date = date(2026, 4, 24),
    period_end: date = date(2026, 5, 7),
) -> EmployeeDiff:
    if diff_days is None:
        diff_days = [
            make_day_diff(date(2026, 4, 24), 480, 450, 30),
        ]
    return EmployeeDiff(
        email=email,
        display_name=display_name,
        diff_days=diff_days,
        period_start=period_start,
        period_end=period_end,
    )


PERIOD_START = date(2026, 4, 24)
PERIOD_END   = date(2026, 5, 7)
EXEC_AT      = datetime(2026, 5, 8, 9, 0, 0)


# ─────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────

class TestFormatDateJp:
    """_format_date_jp のテスト"""

    def test_friday(self):
        assert _format_date_jp(date(2026, 4, 24)) == "4/24(金)"

    def test_saturday(self):
        assert _format_date_jp(date(2026, 5, 2)) == "5/2(土)"

    def test_monday(self):
        assert _format_date_jp(date(2026, 4, 27)) == "4/27(月)"


class TestFormatPeriod:
    """_format_period のテスト"""

    def test_output_format(self):
        result = _format_period(date(2026, 4, 24), date(2026, 5, 7))
        assert result == "2026/04/24〜2026/05/07"


class TestHtmlEscape:
    """_html_escape のテスト"""

    def test_ampersand(self):
        assert _html_escape("A & B") == "A &amp; B"

    def test_less_than(self):
        assert _html_escape("<tag>") == "&lt;tag&gt;"

    def test_double_quote(self):
        assert _html_escape('say "hello"') == "say &quot;hello&quot;"

    def test_single_quote(self):
        assert _html_escape("it's") == "it&#39;s"

    def test_no_special_chars(self):
        assert _html_escape("plain text") == "plain text"


# ─────────────────────────────────────────────
# build_personal_email
# ─────────────────────────────────────────────

class TestBuildPersonalEmail:
    """build_personal_email のテスト"""

    def test_returns_tuple(self):
        """(subject, body_html) のタプルを返すこと"""
        emp = make_employee_diff()
        result = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_subject_contains_period(self):
        """件名に対象期間が含まれること"""
        emp = make_employee_diff()
        subject, _ = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "2026/04/24" in subject
        assert "2026/05/07" in subject

    def test_subject_prefix(self):
        """件名に【勤怠・工数差異】が含まれること"""
        emp = make_employee_diff()
        subject, _ = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert subject.startswith("【勤怠・工数差異】")

    def test_body_contains_display_name(self):
        """本文に宛名（表示名）が含まれること"""
        emp = make_employee_diff(display_name="山田太郎")
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "山田太郎" in body

    def test_body_is_html(self):
        """本文が HTML 形式であること"""
        emp = make_employee_diff()
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert body.strip().startswith("<!DOCTYPE html>")

    def test_body_contains_diff_date(self):
        """本文に差異のある日付が含まれること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(date(2026, 4, 24), 480, 450, 30)]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "4/24" in body

    def test_body_contains_hrmos_time(self):
        """本文にHRMOS勤怠時間が含まれること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(date(2026, 4, 24), 480, 450, 30)]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "8:00" in body

    def test_body_contains_diff_value(self):
        """本文に差異（+0:30）が含まれること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(date(2026, 4, 24), 480, 450, 30)]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "+0:30" in body

    def test_body_shows_miuchiryoku_for_unregistered(self):
        """SUMTIME未登録社員のセルに '未登録' が表示されること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(
                date(2026, 4, 28), 480, None, 480,
                is_sumtime_registered=False,
            )]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "未登録" in body

    def test_body_shows_miuchiryoku_for_registered_no_input(self):
        """SUMTIME登録済みで工数未入力のセルに '未入力' が表示されること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(
                date(2026, 4, 28), 480, None, 480,
                is_sumtime_registered=True,
            )]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "未入力" in body

    def test_body_shows_miudachi_for_no_hrmos(self):
        """勤怠未打刻の場合に '未打刻' が表示されること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(date(2026, 4, 30), None, 240, -240)]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "未打刻" in body

    def test_anomaly_badge_in_body(self):
        """異常値フラグがある場合に本文に警告が表示されること"""
        emp = make_employee_diff(
            diff_days=[make_day_diff(
                date(2026, 4, 24), 1500, 480, 1020,
                is_anomaly=True,
                anomaly_message="勤怠時間が24時間超過（1500分）",
            )]
        )
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "勤怠時間が24時間超過" in body

    def test_display_name_html_escaped(self):
        """表示名に HTML 特殊文字が含まれる場合にエスケープされること"""
        emp = make_employee_diff(display_name="Test <b>User</b>")
        _, body = build_personal_email(emp, PERIOD_START, PERIOD_END)
        assert "<b>User</b>" not in body
        assert "&lt;b&gt;User&lt;/b&gt;" in body


# ─────────────────────────────────────────────
# build_admin_summary_email
# ─────────────────────────────────────────────

class TestBuildAdminSummaryEmail:
    """build_admin_summary_email のテスト"""

    def test_returns_tuple(self):
        """(subject, body_html) のタプルを返すこと"""
        result = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_subject_contains_exec_date(self):
        """件名に実行日が含まれること"""
        subject, _ = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "2026/05/08" in subject

    def test_subject_prefix(self):
        """件名に【勤怠・工数突き合わせ】が含まれること"""
        subject, _ = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "【勤怠・工数突き合わせ】" in subject

    def test_body_contains_notified_count(self):
        """本文に通知人数が含まれること"""
        diffs = [make_employee_diff(), make_employee_diff(email="sato@use-eng.co.jp")]
        _, body = build_admin_summary_email(diffs, PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "2" in body  # 差異検出2名

    def test_body_contains_no_diff_count(self):
        """本文に差異なし人数が含まれること"""
        diffs = [make_employee_diff()]
        _, body = build_admin_summary_email(diffs, PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "9" in body  # 10 - 1 = 9名

    def test_body_contains_employee_names(self):
        """本文に通知対象者の名前が含まれること"""
        diffs = [make_employee_diff(display_name="山田太郎")]
        _, body = build_admin_summary_email(diffs, PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "山田太郎" in body

    def test_body_contains_employee_email(self):
        """本文に通知対象者のメールアドレスが含まれること"""
        diffs = [make_employee_diff(email="yamada@use-eng.co.jp")]
        _, body = build_admin_summary_email(diffs, PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "yamada@use-eng.co.jp" in body

    def test_body_no_diff_message_when_empty(self):
        """差異なし全員の場合に '差異が検出された社員はいません' が表示されること"""
        _, body = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "差異が検出された社員はいませんでした" in body

    def test_body_contains_period(self):
        """本文に対象期間が含まれること"""
        _, body = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "2026/04/24" in body
        assert "2026/05/07" in body

    def test_body_contains_exec_datetime(self):
        """本文に実行日時が含まれること"""
        _, body = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "2026/05/08 09:00" in body

    def test_body_is_html(self):
        """本文が HTML 形式であること"""
        _, body = build_admin_summary_email([], PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert body.strip().startswith("<!DOCTYPE html>")

    def test_diff_days_count_shown(self):
        """通知対象者ごとの差異日数が表示されること"""
        diff_days = [
            make_day_diff(date(2026, 4, 24), 480, 450, 30),
            make_day_diff(date(2026, 4, 28), 480, None, 480),
        ]
        diffs = [make_employee_diff(diff_days=diff_days)]
        _, body = build_admin_summary_email(diffs, PERIOD_START, PERIOD_END, EXEC_AT, 10)
        assert "2日" in body


# ─────────────────────────────────────────────
# build_error_email
# ─────────────────────────────────────────────

class TestBuildErrorEmail:
    """build_error_email のテスト"""

    def test_returns_tuple(self):
        """(subject, body_html) のタプルを返すこと"""
        result = build_error_email("HRMOS API接続失敗", "Connection timeout", EXEC_AT)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_subject_contains_error_keyword(self):
        """件名に【エラー】が含まれること"""
        subject, _ = build_error_email("HRMOS API接続失敗", "detail", EXEC_AT)
        assert "【エラー】" in subject

    def test_body_contains_error_type(self):
        """本文にエラー種別が含まれること"""
        _, body = build_error_email("HRMOS API接続失敗", "Connection timeout", EXEC_AT)
        assert "HRMOS API接続失敗" in body

    def test_body_contains_detail(self):
        """本文にエラー詳細が含まれること"""
        _, body = build_error_email("テスト", "Connection timeout after 3 retries", EXEC_AT)
        assert "Connection timeout after 3 retries" in body

    def test_body_contains_exec_datetime(self):
        """本文に実行日時が含まれること"""
        _, body = build_error_email("テスト", "detail", EXEC_AT)
        assert "2026/05/08 09:00" in body

    def test_executed_at_defaults_to_now(self):
        """executed_at 省略時に現在時刻が使用されること（例外が発生しないこと）"""
        subject, body = build_error_email("テスト", "detail")
        assert subject  # 件名が生成されること
        assert body     # 本文が生成されること

    def test_body_is_html(self):
        """本文が HTML 形式であること"""
        _, body = build_error_email("テスト", "detail", EXEC_AT)
        assert body.strip().startswith("<!DOCTYPE html>")

    def test_detail_html_escaped(self):
        """エラー詳細に HTML 特殊文字が含まれる場合にエスケープされること"""
        _, body = build_error_email("テスト", "<script>alert('xss')</script>", EXEC_AT)
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

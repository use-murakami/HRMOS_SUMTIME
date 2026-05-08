"""
modules/reconciler.py の単体テスト
"""
import pytest
from datetime import date
from modules.hrmos_client import HrmosUser, HrmosWorkOutput
from modules.reconciler import (
    reconcile, DayDiff, EmployeeDiff,
    format_minutes, format_diff,
)


# ─────────────────────────────────────────────
# テスト用ヘルパー
# ─────────────────────────────────────────────

def make_user(email: str, user_id: int = 1, name: str = "テスト 太郎") -> HrmosUser:
    last, first = name.split(" ")
    return HrmosUser(
        user_id=user_id,
        email=email,
        last_name=last,
        first_name=first,
        employee_id=f"A{user_id:04d}",
    )


def make_output(user_id: int, work_date: date, working_minutes: int) -> HrmosWorkOutput:
    return HrmosWorkOutput(
        employee_id=f"A{user_id:04d}",
        user_id=user_id,
        date=work_date,
        working_minutes=working_minutes,
        clock_in="09:00",
        clock_out="18:00",
        break_minutes=60,
        segment="出勤",
    )


PERIOD_START = date(2026, 4, 24)
PERIOD_END = date(2026, 4, 25)
THRESHOLD = 15


# ─────────────────────────────────────────────
# format_minutes
# ─────────────────────────────────────────────

class TestFormatMinutes:
    def test_standard(self):
        assert format_minutes(480) == "8:00"

    def test_with_minutes(self):
        assert format_minutes(90) == "1:30"

    def test_zero(self):
        assert format_minutes(0) == "0:00"

    def test_none_returns_未入力(self):
        assert format_minutes(None) == "未入力"

    def test_negative(self):
        assert format_minutes(-30) == "-0:30"


# ─────────────────────────────────────────────
# format_diff
# ─────────────────────────────────────────────

class TestFormatDiff:
    def test_positive(self):
        assert format_diff(30) == "+0:30"

    def test_negative(self):
        assert format_diff(-480) == "-8:00"

    def test_zero(self):
        assert format_diff(0) == "+0:00"


# ─────────────────────────────────────────────
# reconcile — 基本差異検出
# ─────────────────────────────────────────────

class TestReconcileBasic:
    """基本的な差異検出のテスト"""

    def test_diff_above_threshold_detected(self):
        """閾値以上の差異がある社員が検出されること"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)   # 勤怠 8:00
        sumtime = {"yamada@use-eng.co.jp": {"2026-04-24": 420}}  # 工数 7:00 → 差異 60分

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        assert result[0].email == "yamada@use-eng.co.jp"
        assert len(result[0].diff_days) == 1
        assert result[0].diff_days[0].diff_minutes == 60

    def test_diff_below_threshold_not_detected(self):
        """閾値未満の差異がある社員は検出されないこと"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)   # 勤怠 8:00
        sumtime = {"yamada@use-eng.co.jp": {"2026-04-24": 470}}  # 工数 7:50 → 差異 10分

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 0

    def test_no_diffs_returns_empty(self):
        """全社員で差異がない場合は空リストを返すこと"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)
        sumtime = {"yamada@use-eng.co.jp": {"2026-04-24": 480}}  # 完全一致

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert result == []

    def test_diff_sign_positive_when_hrmos_greater(self):
        """勤怠 > 工数 の場合、diff_minutes が正になること"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)   # 勤怠 8:00
        sumtime = {"a@use-eng.co.jp": {"2026-04-24": 420}}  # 工数 7:00

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert result[0].diff_days[0].diff_minutes > 0

    def test_diff_sign_negative_when_sumtime_greater(self):
        """勤怠 < 工数 の場合、diff_minutes が負になること"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 420)   # 勤怠 7:00
        sumtime = {"a@use-eng.co.jp": {"2026-04-24": 480}}  # 工数 8:00

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert result[0].diff_days[0].diff_minutes < 0


# ─────────────────────────────────────────────
# reconcile — 各差異パターン（仕様書 Section 4.5）
# ─────────────────────────────────────────────

class TestReconcilePatterns:
    """仕様書 Section 4.5 の各パターンのテスト"""

    def test_勤怠あり_工数なし_SUMTIME登録あり(self):
        """勤怠あり・工数なし（SUMTIME登録あり）→ 工数0として差異検出"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)   # 勤怠 8:00
        sumtime = {"yamada@use-eng.co.jp": {}}             # 登録あり・当日レコードなし

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        day = result[0].diff_days[0]
        assert day.hrmos_minutes == 480
        assert day.sumtime_minutes is None
        assert day.diff_minutes == 480       # 勤怠 - 0
        assert day.is_sumtime_registered is True

    def test_勤怠あり_工数なし_SUMTIME未登録(self):
        """勤怠あり・工数なし（SUMTIME未登録）→ 工数0として差異検出"""
        user = make_user("new@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)   # 勤怠 8:00
        sumtime = {}                                       # SUMTIMEにユーザーなし

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        day = result[0].diff_days[0]
        assert day.is_sumtime_registered is False
        assert day.diff_minutes == 480

    def test_工数あり_勤怠なし(self):
        """工数あり・勤怠なし → 差異検出（勤怠未打刻）"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        sumtime = {"yamada@use-eng.co.jp": {"2026-04-24": 240}}  # 工数 4:00
        # hrmos_outputsは空（勤怠レコードなし）

        result = reconcile([user], [], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        day = result[0].diff_days[0]
        assert day.hrmos_minutes is None
        assert day.sumtime_minutes == 240
        assert day.diff_minutes == -240      # 0 - 工数

    def test_勤怠なし_工数なし_SUMTIME未登録_スキップ(self):
        """勤怠なし・工数なし（SUMTIME未登録）→ スキップ"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        sumtime = {}
        # 勤怠も工数もなし

        result = reconcile([user], [], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert result == []

    def test_勤怠なし_工数なし_SUMTIME登録あり_スキップ(self):
        """勤怠なし・工数なし（SUMTIME登録あり）→ スキップ"""
        user = make_user("yamada@use-eng.co.jp", user_id=1)
        sumtime = {"yamada@use-eng.co.jp": {}}  # 登録はあるが当日レコードなし

        result = reconcile([user], [], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert result == []

    def test_exact_threshold_included(self):
        """差異がちょうど閾値の場合は通知対象に含まれること"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)
        sumtime = {"a@use-eng.co.jp": {"2026-04-24": 480 - THRESHOLD}}  # 差異 = 15分

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        assert result[0].diff_days[0].diff_minutes == THRESHOLD


# ─────────────────────────────────────────────
# reconcile — 異常値（仕様書 Section 7.4）
# ─────────────────────────────────────────────

class TestReconcileAnomalies:
    """異常値検出のテスト"""

    def test_hrmos_over_24h_flagged(self):
        """勤怠時間が24時間を超える場合に異常フラグが立つこと"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 1500)  # 25時間 = 1500分（異常）
        sumtime = {"a@use-eng.co.jp": {"2026-04-24": 480}}

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        day = result[0].diff_days[0]
        assert day.is_anomaly is True
        assert "24時間" in day.anomaly_message

    def test_sumtime_negative_flagged(self):
        """工数時間が負の値の場合に異常フラグが立つこと"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)
        sumtime = {"a@use-eng.co.jp": {"2026-04-24": -60}}  # 負の工数（異常）

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert len(result) == 1
        day = result[0].diff_days[0]
        assert day.is_anomaly is True
        assert "負" in day.anomaly_message

    def test_normal_record_no_anomaly_flag(self):
        """正常なレコードには異常フラグが立たないこと"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 24), 480)
        sumtime = {"a@use-eng.co.jp": {"2026-04-24": 420}}

        result = reconcile([user], [output], sumtime, PERIOD_START, PERIOD_END, THRESHOLD)

        assert result[0].diff_days[0].is_anomaly is False
        assert result[0].diff_days[0].anomaly_message == ""


# ─────────────────────────────────────────────
# reconcile — 複数社員・複数日
# ─────────────────────────────────────────────

class TestReconcileMultiple:
    """複数社員・複数日のテスト"""

    def test_multiple_employees_independent(self):
        """複数社員の差異が独立して検出されること"""
        users = [
            make_user("a@use-eng.co.jp", user_id=1),
            make_user("b@use-eng.co.jp", user_id=2),
        ]
        outputs = [
            make_output(1, date(2026, 4, 24), 480),   # a: 差異あり
            make_output(2, date(2026, 4, 24), 480),   # b: 差異なし
        ]
        sumtime = {
            "a@use-eng.co.jp": {"2026-04-24": 420},  # 差異 60分
            "b@use-eng.co.jp": {"2026-04-24": 480},  # 差異 0分
        }

        result = reconcile(users, outputs, sumtime,
                           date(2026, 4, 24), date(2026, 4, 24), THRESHOLD)

        assert len(result) == 1
        assert result[0].email == "a@use-eng.co.jp"

    def test_multiple_diff_days_for_one_employee(self):
        """1社員の複数日の差異がすべて検出されること"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        outputs = [
            make_output(1, date(2026, 4, 24), 480),
            make_output(1, date(2026, 4, 25), 480),
        ]
        sumtime = {
            "a@use-eng.co.jp": {
                "2026-04-24": 420,  # 差異 60分
                "2026-04-25": 300,  # 差異 180分
            }
        }

        result = reconcile(hrmos_users=[user], hrmos_outputs=outputs, sumtime_data=sumtime,
                           period_start=date(2026, 4, 24), period_end=date(2026, 4, 25),
                           threshold_minutes=THRESHOLD)

        assert len(result) == 1
        assert len(result[0].diff_days) == 2

    def test_employee_only_in_sumtime(self):
        """HRMOSに存在しないがSUMTIMEにいる社員も検出されること"""
        # HRMOSユーザー一覧にない、SUMTIMEだけにいるケース（理論上は起こりにくいが対応）
        sumtime = {"ghost@use-eng.co.jp": {"2026-04-24": 480}}

        result = reconcile(
            hrmos_users=[],
            hrmos_outputs=[],
            sumtime_data=sumtime,
            period_start=date(2026, 4, 24),
            period_end=date(2026, 4, 24),
            threshold_minutes=THRESHOLD,
        )

        assert len(result) == 1
        assert result[0].email == "ghost@use-eng.co.jp"
        # 氏名が取れない場合はメールアドレスで代替
        assert result[0].display_name == "ghost@use-eng.co.jp"

    def test_period_only_days_in_range_checked(self):
        """対象期間外の日付のデータは突き合わせに含まれないこと"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        output = make_output(1, date(2026, 4, 23), 480)  # 期間外（1日前）
        sumtime = {"a@use-eng.co.jp": {"2026-04-23": 0}}

        result = reconcile([user], [output], sumtime,
                           period_start=date(2026, 4, 24),  # 期間は4/24から
                           period_end=date(2026, 4, 25),
                           threshold_minutes=THRESHOLD)

        assert result == []

    def test_employee_diff_days_sorted_by_date(self):
        """差異日が日付順に並んでいること"""
        user = make_user("a@use-eng.co.jp", user_id=1)
        outputs = [
            make_output(1, date(2026, 4, 25), 480),
            make_output(1, date(2026, 4, 24), 480),
        ]
        sumtime = {
            "a@use-eng.co.jp": {
                "2026-04-24": 0,
                "2026-04-25": 0,
            }
        }

        result = reconcile(hrmos_users=[user], hrmos_outputs=outputs, sumtime_data=sumtime,
                           period_start=date(2026, 4, 24), period_end=date(2026, 4, 25),
                           threshold_minutes=THRESHOLD)

        dates = [d.date for d in result[0].diff_days]
        assert dates == sorted(dates)

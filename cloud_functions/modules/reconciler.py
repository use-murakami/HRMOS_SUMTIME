"""
突き合わせロジック

HRMOS勤怠データと SUMTIME工数データを日単位で突き合わせ、
閾値を超える差異を持つ社員・日付を検出する。

差異パターン（仕様書 Section 4.5）:
  勤怠 > 工数（≧閾値）          → 工数入力漏れの可能性
  勤怠 < 工数（≧閾値）          → 打刻漏れ or 工数過大入力
  勤怠あり・工数なし（SUMTIME登録あり）→ 工数0として差異あり・通知
  勤怠あり・工数なし（SUMTIME未登録）  → 工数0として差異あり・通知
  工数あり・勤怠なし             → 勤怠未打刻 → 差異あり・通知
  勤怠なし・工数なし             → 通知対象外（スキップ）

異常値（仕様書 Section 7.4）:
  勤怠時間が24時間超過           → 警告フラグ付きで通知
  工数時間が負の値               → 警告フラグ付きで通知
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from modules.hrmos_client import HrmosUser, HrmosWorkOutput
from utils.logger import get_logger

logger = get_logger(__name__)

# 勤怠時間の異常値判定閾値（分）
ANOMALY_HRMOS_MAX_MINUTES = 24 * 60  # 1440分 = 24時間


# ─────────────────────────────────────────────
# データクラス
# ─────────────────────────────────────────────

@dataclass
class DayDiff:
    """1日分の差異情報"""
    date: date
    hrmos_minutes: Optional[int]    # None = 勤怠未打刻（対象勤務区分のレコードなし）
    sumtime_minutes: Optional[int]  # None = 工数未入力 or SUMTIME未登録
    diff_minutes: int               # 勤怠（分）− 工数（分）。正=工数不足、負=勤怠不足
    is_sumtime_registered: bool     # SUMTIMEにユーザーが存在するか
    is_anomaly: bool = False        # 異常値フラグ
    anomaly_message: str = ""       # 異常値の詳細メッセージ


@dataclass
class EmployeeDiff:
    """社員ごとの差異情報（差異がある日のみ収録）"""
    email: str
    display_name: str
    diff_days: list = field(default_factory=list)  # list[DayDiff]
    period_start: date = date.today()
    period_end: date = date.today()


# ─────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────

def format_minutes(minutes: Optional[int]) -> str:
    """
    分（int）を "H:MM" 形式の文字列に変換する。
    None の場合は "未入力" を返す。

    Examples:
        480  → "8:00"
        90   → "1:30"
        None → "未入力"
        0    → "0:00"
    """
    if minutes is None:
        return "未入力"
    sign = "-" if minutes < 0 else ""
    abs_min = abs(minutes)
    h, m = divmod(abs_min, 60)
    return f"{sign}{h}:{m:02d}"


def format_diff(diff_minutes: int) -> str:
    """
    差異（分）を "+H:MM" / "-H:MM" 形式の文字列に変換する。

    Examples:
        30   → "+0:30"
        -480 → "-8:00"
        0    → "+0:00"
    """
    sign = "+" if diff_minutes >= 0 else "-"
    abs_min = abs(diff_minutes)
    h, m = divmod(abs_min, 60)
    return f"{sign}{h}:{m:02d}"


# ─────────────────────────────────────────────
# メイン関数
# ─────────────────────────────────────────────

def reconcile(
    hrmos_users: list,
    hrmos_outputs: list,
    sumtime_data: dict,
    period_start: date,
    period_end: date,
    threshold_minutes: int = 15,
) -> list:
    """
    HRMOS勤怠データと SUMTIME工数データを突き合わせ、差異のある社員リストを返す。

    Args:
        hrmos_users:        HrmosUser のリスト（全社員）
        hrmos_outputs:      HrmosWorkOutput のリスト（対象期間・対象勤務区分でフィルタ済み）
        sumtime_data:       parse_sumtime_records() の出力 {email: {date_str: minutes}}
        period_start:       対象期間の開始日
        period_end:         対象期間の終了日
        threshold_minutes:  差異通知の閾値（分）、デフォルト15分

    Returns:
        差異が検出された社員の EmployeeDiff リスト（差異がない社員は含まない）
    """
    # ── インデックス構築 ────────────────────────────
    user_by_email = {u.email: u for u in hrmos_users}
    user_by_id = {u.user_id: u for u in hrmos_users}

    # HRMOS インデックス: {email: {date_str: minutes}}
    hrmos_index: dict = {}
    for output in hrmos_outputs:
        user = user_by_id.get(output.user_id)
        if user is None:
            logger.warning(f"Unknown user_id in hrmos_outputs: {output.user_id}")
            continue
        email = user.email
        date_str = output.date.isoformat()
        hrmos_index.setdefault(email, {})[date_str] = output.working_minutes

    # 突き合わせ対象の全メールアドレス（HRMOSとSUMTIMEの和集合）
    all_emails = sorted(set(hrmos_index.keys()) | set(sumtime_data.keys()))

    logger.info(
        f"Reconciling {len(all_emails)} employees "
        f"({period_start} - {period_end}, threshold={threshold_minutes}min)"
    )

    # ── 突き合わせ ──────────────────────────────────
    results = []

    for email in all_emails:
        user = user_by_email.get(email)
        display_name = user.display_name if user else email
        is_sumtime_registered = email in sumtime_data

        hrmos_days = hrmos_index.get(email, {})
        sumtime_days = sumtime_data.get(email, {})

        diff_days = []

        # 対象期間の全日付を走査
        current = period_start
        while current <= period_end:
            date_str = current.isoformat()
            hrmos_min = hrmos_days.get(date_str)       # None = 勤怠レコードなし
            sumtime_min = sumtime_days.get(date_str)   # None = 工数レコードなし

            day_diff = _compute_day_diff(
                current, hrmos_min, sumtime_min,
                is_sumtime_registered, threshold_minutes,
            )
            if day_diff is not None:
                diff_days.append(day_diff)

            current += timedelta(days=1)

        if diff_days:
            results.append(EmployeeDiff(
                email=email,
                display_name=display_name,
                diff_days=diff_days,
                period_start=period_start,
                period_end=period_end,
            ))

    logger.info(
        f"Reconciliation done: {len(results)}/{len(all_emails)} employees have diffs"
    )
    return results


# ─────────────────────────────────────────────
# プライベート関数
# ─────────────────────────────────────────────

def _compute_day_diff(
    target_date: date,
    hrmos_min: Optional[int],
    sumtime_min: Optional[int],
    is_sumtime_registered: bool,
    threshold: int,
) -> Optional[DayDiff]:
    """
    1日分の差異を計算し、通知対象なら DayDiff を返す。
    通知対象外（スキップ）なら None を返す。

    Returns:
        DayDiff or None
    """
    # ── 異常値チェック ────────────────────────────
    is_anomaly = False
    anomaly_msgs = []

    if hrmos_min is not None and hrmos_min > ANOMALY_HRMOS_MAX_MINUTES:
        is_anomaly = True
        anomaly_msgs.append(f"勤怠時間が24時間超過（{hrmos_min}分）")

    if sumtime_min is not None and sumtime_min < 0:
        is_anomaly = True
        anomaly_msgs.append(f"工数時間が負の値（{sumtime_min}分）")

    anomaly_message = "、".join(anomaly_msgs)

    # ── パターン判定 ──────────────────────────────
    if hrmos_min is not None:
        # 【勤怠あり】
        # 工数が負の場合は0として扱う（異常値はフラグで管理）
        effective_sumtime = max(sumtime_min, 0) if sumtime_min is not None else 0
        diff = hrmos_min - effective_sumtime

        if abs(diff) >= threshold or is_anomaly:
            return DayDiff(
                date=target_date,
                hrmos_minutes=hrmos_min,
                sumtime_minutes=sumtime_min,
                diff_minutes=diff,
                is_sumtime_registered=is_sumtime_registered,
                is_anomaly=is_anomaly,
                anomaly_message=anomaly_message,
            )

    elif sumtime_min is not None and sumtime_min != 0:
        # 【勤怠なし・工数あり（または工数が異常値）】
        diff = -(abs(sumtime_min))  # 常に負（勤怠不足）

        if abs(diff) >= threshold or is_anomaly:
            return DayDiff(
                date=target_date,
                hrmos_minutes=None,
                sumtime_minutes=sumtime_min,
                diff_minutes=diff,
                is_sumtime_registered=is_sumtime_registered,
                is_anomaly=is_anomaly,
                anomaly_message=anomaly_message,
            )

    else:
        # 【勤怠なし・工数なし】→ スキップ
        pass

    return None

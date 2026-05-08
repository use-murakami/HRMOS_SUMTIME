"""
HRMOS勤怠 API クライアント

機能:
  - トークン取得（Basic認証）
  - ユーザー一覧取得（ページネーション対応）
  - 月次勤怠データ取得（ページネーション・レート制限対応）

ドキュメント: https://ieyasu.co/docs/api.html
"""
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

from utils.logger import get_logger

HRMOS_BASE_URL = "https://ieyasu.co/api/use/v1"

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# データクラス
# ─────────────────────────────────────────────

@dataclass
class HrmosUser:
    """HRMOSユーザー情報"""
    user_id: int
    email: str
    last_name: str
    first_name: str
    employee_id: str  # 社員番号 (number フィールド)

    @property
    def display_name(self) -> str:
        return f"{self.last_name} {self.first_name}"


@dataclass
class HrmosWorkOutput:
    """HRMOS勤怠レコード（1日分）"""
    employee_id: str    # 社員番号
    user_id: int        # HRMOS内部ユーザーID
    date: date          # 勤務日
    working_minutes: int  # 実労働時間（分）
    clock_in: Optional[str]   # 出勤時刻 ("HH:MM")
    clock_out: Optional[str]  # 退勤時刻 ("HH:MM")
    break_minutes: int  # 休憩時間（分）
    segment: str        # 勤務区分 (segment_display_title)


# ─────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────

def parse_hhmm(value: Optional[str]) -> int:
    """
    "H:MM" 形式の文字列を分に変換する。

    Examples:
        "8:00"  → 480
        "1:30"  → 90
        "0:00"  → 0
        None    → 0
        ""      → 0
    """
    if not value:
        return 0
    parts = value.split(":")
    if len(parts) != 2:
        return 0
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 0


def compute_months(period_start: date, period_end: date) -> list:
    """
    対象期間から取得が必要な月リスト（YYYY-MM形式）を返す。

    Examples:
        2026-04-01 〜 2026-04-30 → ["2026-04"]
        2026-03-25 〜 2026-04-07 → ["2026-03", "2026-04"]
    """
    months = []
    year, month = period_start.year, period_start.month
    while (year, month) <= (period_end.year, period_end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


# ─────────────────────────────────────────────
# HRMOSクライアント
# ─────────────────────────────────────────────

class HrmosClient:
    """HRMOS勤怠 API クライアント"""

    def __init__(self, secret_key: str, base_url: str = HRMOS_BASE_URL):
        """
        Args:
            secret_key: HRMOS API Secret Key（Base64済み）
            base_url:   APIベースURL（テスト時にモックURLで上書き可能）
        """
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")

    def get_token(self) -> str:
        """
        HRMOSトークンを取得する。

        Returns:
            トークン文字列（有効期限24時間）

        Raises:
            requests.HTTPError: API呼び出し失敗時
        """
        url = f"{self.base_url}/authentication/token"
        resp = requests.get(
            url,
            headers={"Authorization": f"Basic {self.secret_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json()["token"]
        logger.info("HRMOS token acquired")
        return token

    def get_users(self, token: str) -> list:
        """
        HRMOSユーザー一覧を取得する（ページネーション対応）。

        Args:
            token: HRMOSトークン

        Returns:
            HrmosUser のリスト
        """
        users = []
        page = 1

        while True:
            url = f"{self.base_url}/users"
            resp = self._request_with_retry(token, url, {"limit": 100, "page": page})
            data = resp.json()

            for u in data:
                users.append(HrmosUser(
                    user_id=u["id"],
                    email=u.get("email", ""),
                    last_name=u.get("last_name", ""),
                    first_name=u.get("first_name", ""),
                    employee_id=u.get("number", ""),
                ))

            total_pages = int(resp.headers.get("X-Total-Page", 1))
            logger.info(f"Users: page {page}/{total_pages}, {len(data)} records")

            if page >= total_pages:
                break
            page += 1
            time.sleep(1)

        logger.info(f"Total users: {len(users)}")
        return users

    def get_work_outputs(
        self,
        token: str,
        months: list,
        period_start: date,
        period_end: date,
        target_segments: list,
    ) -> list:
        """
        指定期間の勤怠データを取得する（複数月対応）。

        Args:
            token:            HRMOSトークン
            months:           取得対象月リスト（YYYY-MM形式）
            period_start:     フィルタ開始日
            period_end:       フィルタ終了日
            target_segments:  突き合わせ対象の勤務区分リスト

        Returns:
            HrmosWorkOutput のリスト（period_start〜period_end 内 かつ target_segments に一致するもの）
        """
        all_outputs = []
        for month in months:
            outputs = self._get_monthly_work_outputs(
                token, month, period_start, period_end, target_segments
            )
            all_outputs.extend(outputs)
        logger.info(
            f"Total work outputs: {len(all_outputs)} "
            f"({period_start} - {period_end})"
        )
        return all_outputs

    # ─── プライベートメソッド ───────────────────

    def _get_monthly_work_outputs(
        self,
        token: str,
        month: str,
        period_start: date,
        period_end: date,
        target_segments: list,
    ) -> list:
        """1ヶ月分の勤怠データを取得し、期間・勤務区分でフィルタする。"""
        outputs = []
        page = 1

        while True:
            url = f"{self.base_url}/work_outputs/monthly/{month}"
            resp = self._request_with_retry(
                token, url, {"limit": 100, "page": page}
            )
            data = resp.json()

            for item in data:
                record_date = date.fromisoformat(item["day"])

                # 期間フィルタ
                if not (period_start <= record_date <= period_end):
                    continue

                # 勤務区分フィルタ
                segment = item.get("segment_display_title", "")
                if segment not in target_segments:
                    continue

                outputs.append(HrmosWorkOutput(
                    employee_id=item.get("number", ""),
                    user_id=item.get("user_id", 0),
                    date=record_date,
                    working_minutes=parse_hhmm(item.get("actual_working_hours")),
                    clock_in=item.get("start_at"),
                    clock_out=item.get("end_at"),
                    break_minutes=parse_hhmm(item.get("total_break_time")),
                    segment=segment,
                ))

            total_pages = int(resp.headers.get("X-Total-Page", 1))
            logger.info(
                f"WorkOutputs [{month}]: page {page}/{total_pages}, "
                f"{len(data)} records"
            )

            if page >= total_pages:
                break
            page += 1
            time.sleep(1)

        return outputs

    def _request_with_retry(
        self,
        token: str,
        url: str,
        params: dict,
        max_retries: int = 3,
    ) -> requests.Response:
        """
        Token認証でGETリクエストを実行する。
        HTTP 429（レート制限）時は指数バックオフでリトライする。

        Raises:
            requests.HTTPError: リトライ上限後も失敗した場合
            RuntimeError: レート制限を超えた場合
        """
        for attempt in range(max_retries):
            resp = requests.get(
                url,
                headers={"Authorization": f"Token {token}"},
                params=params,
                timeout=30,
            )

            if resp.status_code == 429:
                wait_sec = 5 * (attempt + 1)
                logger.warning(
                    f"Rate limited (429). Waiting {wait_sec}s... "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_sec)
                continue

            resp.raise_for_status()
            return resp

        raise RuntimeError(
            f"HRMOS API rate limit exceeded after {max_retries} retries: {url}"
        )

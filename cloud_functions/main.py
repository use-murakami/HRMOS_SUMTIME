"""
勤怠・工数突き合わせ自動通知システム — Cloud Functions エントリーポイント

処理フロー:
  1. リクエストパラメータ解析
  2. Secret Manager から認証情報取得
  3. Firestore から設定・除外社員取得
  4. 祝日チェック（production モードのみ）
  5. 対象期間算出
  6. HRMOS勤怠データ取得
  7. SUMTIMEデータ（Cloud Storage）読み込み
  8. 突き合わせ
  9. メール送信（preview=True の場合はスキップ）
 10. 実行結果を Firestore に保存
 11. 管理者サマリーメール送信

呼び出しパラメータ（仕様書 Section 5.5）:
  mode         : "production"（全員）or "test"（特定社員）
  target_email : test 時のみ必須
  period_days  : 遡る日数（省略時: Firestoreの設定値 or 14）
  period_month : 対象月（"YYYY-MM" 形式）。period_days と同時指定不可
  preview      : true の場合メール送信をスキップ（管理UIのプレビュー用）
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

import flask
import functions_framework
import jpholiday
from google.cloud import firestore

import config
from modules.email_builder import (
    build_admin_summary_email,
    build_error_email,
    build_personal_email,
)
from modules.email_client import EmailClient, EmailMessage
from modules.hrmos_client import HrmosClient, compute_months
from modules.reconciler import EmployeeDiff, reconcile
from modules.storage_client import SumtimeDataNotFoundError, load_sumtime_data, parse_sumtime_records
from utils.firestore_client import (
    load_excluded_emails,
    load_settings,
    save_execution_result,
)
from utils.logger import get_logger
from utils.secret_manager import load_all_secrets

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# Cloud Functions エントリーポイント
# ─────────────────────────────────────────────

@functions_framework.http
def run(request: flask.Request) -> tuple[flask.Response, int]:
    """
    Cloud Functions HTTP トリガーのエントリーポイント。
    """
    executed_at = datetime.now()
    logger.info(f"=== 突き合わせ処理 開始: {executed_at.isoformat()} ===")

    # ── Step 1: パラメータ解析 ────────────────────────────────────
    try:
        params = _parse_params(request)
    except ValueError as e:
        logger.error(f"Invalid parameters: {e}")
        return flask.make_response(
            flask.jsonify({"error": str(e)}), 400
        )

    mode         = params["mode"]
    target_email = params.get("target_email")
    period_days  = params.get("period_days")
    period_month = params.get("period_month")
    is_preview   = params.get("preview", False)

    logger.info(
        f"Parameters: mode={mode}, target_email={target_email}, "
        f"period_days={period_days}, period_month={period_month}, "
        f"preview={is_preview}"
    )

    # ── Step 2: Secret Manager から認証情報取得 ──────────────────
    try:
        secrets = load_all_secrets(config.GCP_PROJECT_ID)
    except Exception as e:
        return _handle_fatal_error("Secret Manager 接続失敗", e, executed_at)

    # ── Step 3: Firestore から設定・除外社員取得 ─────────────────
    db = firestore.Client(project=config.GCP_PROJECT_ID)
    try:
        fs_settings    = load_settings(db)
        excluded_emails = load_excluded_emails(db)
    except Exception as e:
        logger.warning(f"Firestore load failed. Using defaults: {e}")
        fs_settings    = {"threshold_minutes": 15, "period_days": 14}
        excluded_emails = set()

    # パラメータ優先、未指定時は Firestore → config のデフォルト値
    threshold_minutes = fs_settings["threshold_minutes"]
    if period_days is None and period_month is None:
        period_days = fs_settings["period_days"]

    # ── Step 4: 対象期間算出 ──────────────────────────────────────
    try:
        period_start, period_end = _calc_period(period_days, period_month)
    except ValueError as e:
        return flask.make_response(flask.jsonify({"error": str(e)}), 400)

    logger.info(f"Period: {period_start} 〜 {period_end}, threshold={threshold_minutes}min")

    # ── Step 5: 祝日チェック（production モード、プレビューなし） ──
    if mode == "production" and not is_preview:
        today = date.today()
        if jpholiday.is_holiday(today):
            msg = f"本日（{today}）は祝日のためスキップします"
            logger.info(msg)
            return flask.make_response(flask.jsonify({"skipped": msg}), 200)

    # ── Step 6: HRMOS勤怠データ取得 ─────────────────────────────
    hrmos_client = HrmosClient(
        secret_key=secrets["hrmos-secret-key"],
    )
    try:
        token        = hrmos_client.get_token()
        hrmos_users  = hrmos_client.get_users(token)
        months       = compute_months(period_start, period_end)
        hrmos_outputs = hrmos_client.get_work_outputs(
            token, months, period_start, period_end,
            target_segments=config.TARGET_WORK_SEGMENTS,
        )
    except Exception as e:
        return _handle_fatal_error("HRMOS API 接続失敗", e, executed_at, secrets)

    logger.info(f"HRMOS: {len(hrmos_users)} users, {len(hrmos_outputs)} records")

    # ── Step 7: SUMTIMEデータ読み込み ────────────────────────────
    try:
        raw_sumtime  = load_sumtime_data(config.GCS_BUCKET_NAME)
        sumtime_data = parse_sumtime_records(raw_sumtime["records"])
    except SumtimeDataNotFoundError as e:
        return _handle_fatal_error("SUMTIMEデータ取得失敗", e, executed_at, secrets)
    except Exception as e:
        return _handle_fatal_error("Cloud Storage 接続失敗", e, executed_at, secrets)

    logger.info(f"SUMTIME: {len(sumtime_data)} employees")

    # ── Step 8: 除外社員フィルタ + 突き合わせ ───────────────────
    # test モードの場合は対象社員を1名に絞る
    if mode == "test" and target_email:
        hrmos_users   = [u for u in hrmos_users if u.email == target_email]
        hrmos_outputs = [o for o in hrmos_outputs
                         if any(u.user_id == o.user_id for u in hrmos_users)]
        sumtime_data  = {k: v for k, v in sumtime_data.items() if k == target_email}

    # 除外社員を除去
    if excluded_emails:
        hrmos_users   = [u for u in hrmos_users if u.email not in excluded_emails]
        hrmos_outputs = [o for o in hrmos_outputs
                         if any(u.user_id == o.user_id for u in hrmos_users)]
        sumtime_data  = {k: v for k, v in sumtime_data.items()
                         if k not in excluded_emails}

    diff_results = reconcile(
        hrmos_users=hrmos_users,
        hrmos_outputs=hrmos_outputs,
        sumtime_data=sumtime_data,
        period_start=period_start,
        period_end=period_end,
        threshold_minutes=threshold_minutes,
    )

    total_employees = len(set(u.email for u in hrmos_users) | set(sumtime_data.keys()))
    logger.info(
        f"Reconcile done: {len(diff_results)}/{total_employees} employees have diffs"
    )

    # ── Step 9: プレビューモードの場合はここで返す ───────────────
    if is_preview:
        preview_data = _build_preview_response(
            diff_results, period_start, period_end, total_employees
        )
        logger.info("Preview mode: skipping email sending")
        return flask.make_response(flask.jsonify(preview_data), 200)

    # ── Step 10: 個人向けメール送信 ───────────────────────────────
    email_client = EmailClient(
        tenant_id=secrets["azure-tenant-id"],
        client_id=secrets["azure-client-id"],
        client_secret=secrets["azure-client-secret"],
        sender_email=config.SENDER_EMAIL,
    )

    send_errors = []
    if diff_results:
        messages = [
            EmailMessage(
                to_address=emp.email,
                subject=subject,
                body_html=body_html,
            )
            for emp in diff_results
            for subject, body_html in [build_personal_email(emp, period_start, period_end)]
        ]
        failed = email_client.send_emails(messages)
        if failed:
            send_errors.append(f"個人メール送信失敗: {failed}")
            logger.error(f"Personal email send failures: {failed}")

    # ── Step 11: Firestore に実行結果を保存 ───────────────────────
    notified_employees_data = [
        {
            "email":           emp.email,
            "display_name":    emp.display_name,
            "diff_days_count": len(emp.diff_days),
        }
        for emp in diff_results
    ]

    try:
        save_execution_result(
            db=db,
            executed_at=executed_at,
            period_start=period_start,
            period_end=period_end,
            mode=mode,
            is_preview=False,
            total_employees=total_employees,
            notified_count=len(diff_results),
            notified_employees=notified_employees_data,
            errors=send_errors,
        )
    except Exception as e:
        logger.error(f"Firestore save failed: {e}")
        send_errors.append(f"Firestore 保存失敗: {e}")

    # ── Step 12: 管理者サマリーメール送信 ─────────────────────────
    try:
        summary_subject, summary_body = build_admin_summary_email(
            diff_results=diff_results,
            period_start=period_start,
            period_end=period_end,
            executed_at=executed_at,
            total_employees=total_employees,
        )
        email_client.send_email(EmailMessage(
            to_address=config.ADMIN_EMAIL,
            subject=summary_subject,
            body_html=summary_body,
        ))
    except Exception as e:
        logger.error(f"Admin summary email failed: {e}")
        send_errors.append(f"管理者サマリーメール送信失敗: {e}")

    # ── 完了 ────────────────────────────────────────────────────
    result = {
        "status":           "ok",
        "period_start":     period_start.isoformat(),
        "period_end":       period_end.isoformat(),
        "total_employees":  total_employees,
        "notified_count":   len(diff_results),
        "errors":           send_errors,
    }
    logger.info(f"=== 突き合わせ処理 完了: {result} ===")
    return flask.make_response(flask.jsonify(result), 200)


# ─────────────────────────────────────────────
# プライベート関数
# ─────────────────────────────────────────────

def _parse_params(request: flask.Request) -> dict:
    """
    リクエストからパラメータを解析する。

    Returns:
        パラメータの dict

    Raises:
        ValueError: パラメータが不正な場合
    """
    body = request.get_json(silent=True) or {}

    mode = body.get("mode", "")
    if mode not in ("production", "test"):
        raise ValueError(f"mode は 'production' または 'test' を指定してください: {mode!r}")

    if mode == "test" and not body.get("target_email"):
        raise ValueError("test モードでは target_email が必須です")

    period_days  = body.get("period_days")
    period_month = body.get("period_month")

    if period_days is not None and period_month is not None:
        raise ValueError("period_days と period_month は同時に指定できません")

    if period_days is not None:
        try:
            period_days = int(period_days)
            if period_days <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError(f"period_days は正の整数を指定してください: {period_days!r}")

    if period_month is not None:
        import re
        if not re.match(r"^\d{4}-\d{2}$", str(period_month)):
            raise ValueError(f"period_month は YYYY-MM 形式で指定してください: {period_month!r}")

    return {
        "mode":         mode,
        "target_email": body.get("target_email"),
        "period_days":  period_days,
        "period_month": period_month,
        "preview":      bool(body.get("preview", False)),
    }


def _calc_period(
    period_days: Optional[int],
    period_month: Optional[str],
) -> tuple[date, date]:
    """
    パラメータから対象期間（開始日・終了日）を算出する。

    Returns:
        (period_start, period_end) のタプル

    Raises:
        ValueError: period_month の形式が不正な場合
    """
    today = date.today()

    if period_month is not None:
        # 月指定: 指定月の1日〜末日
        import calendar
        year, month = map(int, period_month.split("-"))
        period_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        period_end = date(year, month, last_day)
    else:
        # 日数指定（デフォルト: 14日）
        days = period_days or 14
        period_end   = today - timedelta(days=1)
        period_start = today - timedelta(days=days)

    return period_start, period_end


def _handle_fatal_error(
    error_type: str,
    exception: Exception,
    executed_at: datetime,
    secrets: Optional[dict] = None,
) -> tuple[flask.Response, int]:
    """
    致命的エラー発生時に管理者メールを送信してエラーレスポンスを返す。
    """
    detail = f"{type(exception).__name__}: {exception}"
    logger.error(f"Fatal error [{error_type}]: {detail}")

    if secrets:
        try:
            email_client = EmailClient(
                tenant_id=secrets["azure-tenant-id"],
                client_id=secrets["azure-client-id"],
                client_secret=secrets["azure-client-secret"],
                sender_email=config.SENDER_EMAIL,
            )
            subject, body_html = build_error_email(error_type, detail, executed_at)
            email_client.send_email(EmailMessage(
                to_address=config.ADMIN_EMAIL,
                subject=subject,
                body_html=body_html,
            ))
        except Exception as mail_err:
            logger.error(f"Error email also failed: {mail_err}")

    return flask.make_response(
        flask.jsonify({"error": error_type, "detail": detail}), 500
    )


def _build_preview_response(
    diff_results: list[EmployeeDiff],
    period_start: date,
    period_end: date,
    total_employees: int,
) -> dict:
    """
    プレビューモード用のレスポンスデータを生成する。
    """
    return {
        "status":          "preview",
        "period_start":    period_start.isoformat(),
        "period_end":      period_end.isoformat(),
        "total_employees": total_employees,
        "notified_count":  len(diff_results),
        "diff_results": [
            {
                "email":           emp.email,
                "display_name":    emp.display_name,
                "diff_days_count": len(emp.diff_days),
                "diff_days": [
                    {
                        "date":             d.date.isoformat(),
                        "hrmos_minutes":    d.hrmos_minutes,
                        "sumtime_minutes":  d.sumtime_minutes,
                        "diff_minutes":     d.diff_minutes,
                        "is_anomaly":       d.is_anomaly,
                        "anomaly_message":  d.anomaly_message,
                    }
                    for d in emp.diff_days
                ],
            }
            for emp in diff_results
        ],
    }

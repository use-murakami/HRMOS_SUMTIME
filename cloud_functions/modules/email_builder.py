"""
メール本文（HTML）生成モジュール

仕様書 Section 5.3〜5.4・7.1 に基づき、3種類のメールを生成する。

  build_personal_email()      — 個人向け差異通知メール
  build_admin_summary_email() — 管理者サマリーメール
  build_error_email()         — エラー通知メール

いずれも (subject: str, body_html: str) のタプルを返す。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from modules.reconciler import DayDiff, EmployeeDiff, format_diff, format_minutes

# 送信元・管理者アドレス（メール本文の固定文言で使用）
SENDER_EMAIL = "kintai-notice@use-eng.co.jp"
ADMIN_EMAIL  = "y-murakami@use-eng.co.jp"

# HTMLテンプレート共通スタイル
_CSS = """
body {
    font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', Meiryo, sans-serif;
    font-size: 14px;
    color: #333333;
    margin: 0;
    padding: 20px;
    background-color: #f5f5f5;
}
.container {
    max-width: 700px;
    margin: 0 auto;
    background-color: #ffffff;
    border: 1px solid #dddddd;
    border-radius: 4px;
    padding: 24px 32px;
}
h2 {
    font-size: 16px;
    color: #333333;
    border-bottom: 2px solid #e0e0e0;
    padding-bottom: 8px;
    margin-top: 24px;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
}
th {
    background-color: #f0f0f0;
    color: #555555;
    font-weight: bold;
    padding: 8px 12px;
    border: 1px solid #cccccc;
    text-align: center;
}
td {
    padding: 7px 12px;
    border: 1px solid #cccccc;
    text-align: center;
}
.diff-value {
    color: #cc0000;
    font-weight: bold;
}
.anomaly-row {
    background-color: #fff3cd;
}
.anomaly-badge {
    font-size: 11px;
    color: #856404;
    background-color: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 3px;
    padding: 1px 5px;
    margin-left: 4px;
}
.footer {
    margin-top: 24px;
    font-size: 12px;
    color: #888888;
    border-top: 1px solid #eeeeee;
    padding-top: 12px;
}
.summary-list {
    list-style: none;
    padding: 0;
    margin: 8px 0;
}
.summary-list li {
    padding: 4px 0;
    border-bottom: 1px solid #eeeeee;
}
.count-box {
    display: inline-block;
    background-color: #f8f8f8;
    border: 1px solid #dddddd;
    border-radius: 4px;
    padding: 12px 20px;
    margin: 8px 4px;
}
.count-label {
    font-size: 12px;
    color: #777777;
}
.count-value {
    font-size: 22px;
    font-weight: bold;
    color: #333333;
}
"""


# ─────────────────────────────────────────────
# 個人向けメール
# ─────────────────────────────────────────────

def build_personal_email(
    emp: EmployeeDiff,
    period_start: date,
    period_end: date,
) -> tuple[str, str]:
    """
    個人向け差異通知メールの (subject, body_html) を生成する。

    Args:
        emp:          差異情報（EmployeeDiff）
        period_start: 対象期間の開始日
        period_end:   対象期間の終了日

    Returns:
        (subject, body_html) のタプル
    """
    period_str = _format_period(period_start, period_end)
    subject = f"【勤怠・工数差異】確認をお願いします（対象期間: {period_str}）"

    rows_html = "\n".join(_build_day_diff_row(d) for d in emp.diff_days)

    body_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <p>{_html_escape(emp.display_name)} さん</p>
  <p>
    以下の期間で勤怠時間と工数の差異が検出されました。<br>
    ご確認のうえ、修正をお願いします。
  </p>
  <p><strong>対象期間:</strong> {_format_period_long(period_start, period_end)}</p>

  <table>
    <thead>
      <tr>
        <th>日付</th>
        <th>HRMOS勤怠</th>
        <th>SUMTIME工数</th>
        <th>差異</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>

  <p style="font-size: 12px; color: #666666; margin-top: 16px;">
    ※ 差異はすべて赤字で表示しています。+は勤怠超過（工数不足）、-は工数超過（勤怠不足）<br>
    ※ 15分以上の差異がある日のみ表示しています<br>
    ※ 差異が解消されると通知は停止します
  </p>

  <div class="footer">
    このメールは自動送信です。返信は不要です。<br>
    ご不明な点は管理者（{ADMIN_EMAIL}）にお問い合わせください。
  </div>
</div>
</body>
</html>"""

    return subject, body_html


def _build_day_diff_row(d: DayDiff) -> str:
    """1日分の差異テーブル行 HTML を生成する。"""
    date_str   = _format_date_jp(d.date)
    hrmos_str  = format_minutes(d.hrmos_minutes) if d.hrmos_minutes is not None else "未打刻"
    sumtime_str = _format_sumtime_cell(d)
    diff_str   = format_diff(d.diff_minutes)

    row_class = ' class="anomaly-row"' if d.is_anomaly else ""
    anomaly_badge = (
        f'<span class="anomaly-badge">⚠ {_html_escape(d.anomaly_message)}</span>'
        if d.is_anomaly else ""
    )

    return (
        f'      <tr{row_class}>'
        f'<td>{date_str}</td>'
        f'<td>{_html_escape(hrmos_str)}</td>'
        f'<td>{_html_escape(sumtime_str)}</td>'
        f'<td><span class="diff-value">{_html_escape(diff_str)}</span>{anomaly_badge}</td>'
        f'</tr>'
    )


def _format_sumtime_cell(d: DayDiff) -> str:
    """SUMTIME工数セルの表示文字列を返す。"""
    if d.sumtime_minutes is None:
        if d.is_sumtime_registered:
            return "未入力"
        else:
            return "未登録"
    return format_minutes(d.sumtime_minutes)


# ─────────────────────────────────────────────
# 管理者サマリーメール
# ─────────────────────────────────────────────

def build_admin_summary_email(
    diff_results: list[EmployeeDiff],
    period_start: date,
    period_end: date,
    executed_at: datetime,
    total_employees: int,
) -> tuple[str, str]:
    """
    管理者サマリーメールの (subject, body_html) を生成する。

    Args:
        diff_results:      差異が検出された社員リスト
        period_start:      対象期間の開始日
        period_end:        対象期間の終了日
        executed_at:       実行日時
        total_employees:   突き合わせ対象の全社員数

    Returns:
        (subject, body_html) のタプル
    """
    exec_date_str = executed_at.strftime("%Y/%m/%d")
    subject = f"【勤怠・工数突き合わせ】実行結果（{exec_date_str}）"

    notified_count = len(diff_results)
    no_diff_count  = total_employees - notified_count

    # 通知対象者リスト HTML
    if diff_results:
        names_html = "\n".join(
            f'      <li>{_html_escape(emp.display_name)}（{_html_escape(emp.email)}）'
            f' — {len(emp.diff_days)}日</li>'
            for emp in diff_results
        )
        names_section = f"""
  <h2>通知対象者</h2>
  <ul class="summary-list">
{names_html}
  </ul>"""
    else:
        names_section = """
  <h2>通知対象者</h2>
  <p style="color: #666666;">差異が検出された社員はいませんでした。</p>"""

    body_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <p>
    <strong>対象期間:</strong> {_format_period_long(period_start, period_end)}<br>
    <strong>実行日時:</strong> {executed_at.strftime("%Y/%m/%d %H:%M")}
  </p>

  <h2>通知結果</h2>
  <div>
    <div class="count-box">
      <div class="count-label">差異検出・通知済み</div>
      <div class="count-value">{notified_count}名</div>
    </div>
    <div class="count-box">
      <div class="count-label">差異なし（通知なし）</div>
      <div class="count-value">{no_diff_count}名</div>
    </div>
  </div>
{names_section}

  <div class="footer">
    このメールは自動送信です。
  </div>
</div>
</body>
</html>"""

    return subject, body_html


# ─────────────────────────────────────────────
# エラー通知メール
# ─────────────────────────────────────────────

def build_error_email(
    error_type: str,
    detail: str,
    executed_at: Optional[datetime] = None,
) -> tuple[str, str]:
    """
    管理者向けエラー通知メールの (subject, body_html) を生成する。

    Args:
        error_type:   エラー種別（例: "HRMOS API接続失敗"）
        detail:       エラーの詳細メッセージ
        executed_at:  実行日時（省略時は現在時刻）

    Returns:
        (subject, body_html) のタプル
    """
    if executed_at is None:
        executed_at = datetime.now()

    subject = "【エラー】勤怠・工数突き合わせシステム 異常検知"

    body_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>{_CSS}</style>
</head>
<body>
<div class="container">
  <p style="color: #cc0000; font-weight: bold;">
    勤怠・工数突き合わせシステムでエラーが発生しました。
  </p>

  <table>
    <tbody>
      <tr>
        <th style="text-align: left; width: 120px;">実行日時</th>
        <td style="text-align: left;">{executed_at.strftime("%Y/%m/%d %H:%M")}</td>
      </tr>
      <tr>
        <th style="text-align: left;">エラー種別</th>
        <td style="text-align: left;">{_html_escape(error_type)}</td>
      </tr>
      <tr>
        <th style="text-align: left;">詳細</th>
        <td style="text-align: left; font-family: monospace; white-space: pre-wrap;">{_html_escape(detail)}</td>
      </tr>
    </tbody>
  </table>

  <p>Cloud Logging でエラーの詳細を確認してください。</p>

  <div class="footer">
    このメールは自動送信です。
  </div>
</div>
</body>
</html>"""

    return subject, body_html


# ─────────────────────────────────────────────
# プライベート関数
# ─────────────────────────────────────────────

def _format_period(start: date, end: date) -> str:
    """'2026/04/24〜2026/05/07' 形式の文字列を返す。"""
    return f"{start.strftime('%Y/%m/%d')}〜{end.strftime('%Y/%m/%d')}"


def _format_period_long(start: date, end: date) -> str:
    """'2026/04/24 〜 2026/05/07' 形式の文字列を返す。"""
    return f"{start.strftime('%Y/%m/%d')} 〜 {end.strftime('%Y/%m/%d')}"


_WEEKDAY_JP = ("月", "火", "水", "木", "金", "土", "日")


def _format_date_jp(d: date) -> str:
    """'4/24(金)' 形式の文字列を返す。"""
    wd = _WEEKDAY_JP[d.weekday()]
    return f"{d.month}/{d.day}({wd})"


def _html_escape(text: str) -> str:
    """HTML 特殊文字をエスケープする。"""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

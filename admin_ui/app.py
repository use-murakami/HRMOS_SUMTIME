"""
勤怠・工数突き合わせシステム — 管理UI
Flask アプリケーション（Cloud Run デプロイ用）

認証: Basic認証（パスワードは Secret Manager で管理）
"""
from __future__ import annotations

import json
import os
import base64
import functools
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from google.cloud import firestore

import config
from utils.secret_manager import get_secret
from utils.hrmos_client import get_hrmos_users

app = Flask(__name__)

# ─────────────────────────────────────────────
# Basic認証
# ─────────────────────────────────────────────

def _get_admin_password() -> str:
    """Secret Manager から管理UIパスワードを取得する（起動時にキャッシュ）"""
    if not hasattr(_get_admin_password, "_cache"):
        try:
            _get_admin_password._cache = get_secret(
                config.GCP_PROJECT_ID, "admin-ui-password"
            )
        except Exception:
            # ローカル開発時はデフォルトパスワードを使用
            _get_admin_password._cache = os.environ.get("ADMIN_UI_PASSWORD", "changeme")
    return _get_admin_password._cache


def require_auth(f):
    """Basic認証デコレータ"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth:
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="Admin UI"'},
            )
        expected_user = config.ADMIN_UI_USER
        expected_pass = _get_admin_password()
        if auth.username != expected_user or auth.password != expected_pass:
            return Response(
                "Invalid credentials",
                401,
                {"WWW-Authenticate": 'Basic realm="Admin UI"'},
            )
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# Firestore クライアント（リクエスト毎に再利用）
# ─────────────────────────────────────────────

def get_db() -> firestore.Client:
    if not hasattr(app, "_db"):
        app._db = firestore.Client(project=config.GCP_PROJECT_ID)
    return app._db


# ─────────────────────────────────────────────
# ページルート
# ─────────────────────────────────────────────

@app.route("/")
@require_auth
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@require_auth
def dashboard():
    db = get_db()
    # 直近10件の実行結果を取得
    results = _load_recent_executions(db, limit=10)
    # 最新の実行結果（サマリー用）
    latest = results[0] if results else None
    return render_template(
        "dashboard.html",
        recent_results=results,
        latest=latest,
        testing_mode=config.TESTING_MODE,
    )


@app.route("/run")
@require_auth
def run_page():
    return render_template(
        "run.html",
        testing_mode=config.TESTING_MODE,
        config=config,
    )


@app.route("/employees")
@require_auth
def employees_page():
    db = get_db()
    employees = _load_employees_with_status(db)
    return render_template(
        "employees.html",
        employees=employees,
        testing_mode=config.TESTING_MODE,
        admin_email=config.ADMIN_EMAIL,
        on_count=sum(1 for e in employees if e["notify"]),
        off_count=sum(1 for e in employees if not e["notify"]),
    )


@app.route("/settings")
@require_auth
def settings_page():
    db = get_db()
    settings = _load_settings(db)
    return render_template(
        "settings.html",
        settings=settings,
        testing_mode=config.TESTING_MODE,
    )


# ─────────────────────────────────────────────
# API エンドポイント
# ─────────────────────────────────────────────

@app.route("/api/run", methods=["POST"])
@require_auth
def api_run():
    """Cloud Functions を呼び出して突き合わせを実行する"""
    body = request.get_json(silent=True) or {}

    # テストモード時の「管理者のみ」: mode=test + 管理者アドレスをサーバ側で注入
    # （対象アドレスはクライアントから任意指定させず、必ず config.ADMIN_EMAIL を使う）
    if body.pop("admin_only", False):
        body["mode"] = "test"
        body["target_email"] = config.ADMIN_EMAIL

    try:
        resp = _call_cloud_function(body)
        return jsonify(resp), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employees/<email>/notify", methods=["PUT"])
@require_auth
def api_update_notify(email: str):
    """社員の通知設定を更新する（TESTING_MODE中は管理者のみ）"""
    body = request.get_json(silent=True) or {}
    notify: bool = bool(body.get("notify", True))

    # TESTING_MODE中は管理者アドレス以外の変更を拒否
    if config.TESTING_MODE and email != config.ADMIN_EMAIL:
        return jsonify({
            "error": "テストモード中は管理者以外の通知設定を変更できません",
            "testing_mode": True,
        }), 403

    db = get_db()
    _update_employee_notify(db, email, notify)
    return jsonify({"email": email, "notify": notify}), 200


@app.route("/api/settings", methods=["PUT"])
@require_auth
def api_update_settings():
    """設定を更新する"""
    body = request.get_json(silent=True) or {}
    db = get_db()

    threshold = int(body.get("threshold_minutes", 15))
    period_days = int(body.get("period_days", 14))

    db.collection("settings").document("main").set({
        "threshold_minutes": threshold,
        "period_days":       period_days,
        "updated_at":        datetime.now(timezone.utc),
    }, merge=True)

    return jsonify({
        "threshold_minutes": threshold,
        "period_days":       period_days,
    }), 200


@app.route("/api/executions")
@require_auth
def api_executions():
    """実行履歴を返す"""
    db = get_db()
    limit = int(request.args.get("limit", 20))
    results = _load_recent_executions(db, limit=limit)
    return jsonify(results), 200


# ─────────────────────────────────────────────
# ヘルスチェック（認証なし）
# ─────────────────────────────────────────────

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────
# プライベート関数
# ─────────────────────────────────────────────

def _call_cloud_function(body: dict) -> dict:
    """Cloud Functions HTTP エンドポイントを呼び出す"""
    url = config.CLOUD_FUNCTION_URL
    if not url:
        raise ValueError("CLOUD_FUNCTION_URL が設定されていません")

    headers = {"Content-Type": "application/json"}

    # Cloud Run → Cloud Functions 間の認証（OIDC トークン）
    # Cloud Run では自動的に ID トークンが取得可能
    try:
        import google.auth
        import google.auth.transport.requests
        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        # Compute Engine / Cloud Run では identity token を別途取得
        token_url = (
            f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/"
            f"default/identity?audience={url}"
        )
        token_resp = requests.get(token_url, headers={"Metadata-Flavor": "Google"}, timeout=5)
        if token_resp.ok:
            headers["Authorization"] = f"Bearer {token_resp.text}"
    except Exception:
        pass  # ローカル開発環境では認証なしで呼び出し

    resp = requests.post(url, json=body, headers=headers, timeout=360)
    resp.raise_for_status()
    return resp.json()


def _load_recent_executions(db: firestore.Client, limit: int = 10) -> list[dict]:
    """Firestore から直近の実行結果を取得する"""
    try:
        docs = (
            db.collection("execution_results")
            .order_by("executed_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = []
        for doc in docs:
            d = doc.to_dict()
            # datetime を文字列に変換
            if "executed_at" in d and hasattr(d["executed_at"], "isoformat"):
                d["executed_at"] = d["executed_at"].isoformat()
            if "period_start" in d and hasattr(d["period_start"], "isoformat"):
                d["period_start"] = d["period_start"].isoformat()
            if "period_end" in d and hasattr(d["period_end"], "isoformat"):
                d["period_end"] = d["period_end"].isoformat()
            d["id"] = doc.id
            results.append(d)
        return results
    except Exception:
        return []


def _load_employees_with_status(db: firestore.Client) -> list[dict]:
    """
    HRMOS API から社員一覧を取得し、Firestore の excluded_employees と
    突き合わせて通知ON/OFFを付けて返す。
    """
    # excluded_emails: Firestore に存在する = 通知OFF
    try:
        excluded_docs = db.collection("excluded_employees").stream()
        excluded_emails = {doc.id for doc in excluded_docs}
    except Exception:
        excluded_emails = set()

    # HRMOS から社員一覧取得
    try:
        import json
        raw = get_secret(config.GCP_PROJECT_ID, "hrmos-credentials")
        hrmos_secret_key = json.loads(raw)["secret_key"]
        hrmos_users = get_hrmos_users(hrmos_secret_key)
    except Exception as e:
        # HRMOS 取得失敗時は excluded_employees のみを表示
        hrmos_users = [
            {"email": email, "display_name": email.split("@")[0], "user_id": None}
            for email in excluded_emails
        ]

    # 通知ON/OFF を付与してソート（管理者を先頭、残りは社員番号順）
    employees = []
    for u in hrmos_users:
        email = u["email"]
        employees.append({
            "email":        email,
            "name":         u["display_name"] or email.split("@")[0],
            "notify":       email not in excluded_emails,
            "is_admin":     email == config.ADMIN_EMAIL,
            "employee_id":  u.get("employee_id", ""),
        })

    # 管理者を先頭、残りは社員番号順
    employees.sort(key=lambda e: (not e["is_admin"], e["employee_id"]))
    return employees


def _load_settings(db: firestore.Client) -> dict:
    """Firestore から設定を取得する"""
    try:
        doc = db.collection("settings").document("main").get()
        if doc.exists:
            data = doc.to_dict()
            return {
                "threshold_minutes": int(data.get("threshold_minutes", 15)),
                "period_days":       int(data.get("period_days", 14)),
            }
    except Exception:
        pass
    return {"threshold_minutes": 15, "period_days": 14}


def _update_employee_notify(db: firestore.Client, email: str, notify: bool) -> None:
    """社員の通知設定を更新する"""
    ref = db.collection("excluded_employees").document(email)
    if notify:
        # excluded_employees から削除 = 通知ON
        ref.delete()
    else:
        # excluded_employees に追加 = 通知OFF
        ref.set({"updated_at": datetime.now(timezone.utc)})


if __name__ == "__main__":
    # ローカル開発用
    app.run(host="0.0.0.0", port=8080, debug=True)

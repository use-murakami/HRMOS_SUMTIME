#!/bin/bash
# ============================================================
# Cloud Scheduler セットアップスクリプト
# 用途: 定期実行ジョブの登録（3ジョブ）
# 前提: deploy_cloud_functions.sh 実行済みであること
#
# 使い方:
#   bash scripts/setup_cloud_scheduler.sh
# ============================================================

set -euo pipefail

# ── 設定 ─────────────────────────────────────────────────────
PROJECT_ID="kintai-kosu-notification"
REGION="asia-northeast1"
FUNCTION_NAME="kintai-reconcile"
TIMEZONE="Asia/Tokyo"

# Cloud Functions を呼び出す際のサービスアカウント
# （Default compute SA。Cloud Functions Invoker 権限が必要）
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
SCHEDULER_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# ── 関数URLを取得 ─────────────────────────────────────────────
FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
  --gen2 \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(serviceConfig.uri)")

echo "======================================================"
echo "  Cloud Scheduler セットアップ"
echo "======================================================"
echo "  プロジェクト    : ${PROJECT_ID}"
echo "  リージョン      : ${REGION}"
echo "  関数URL         : ${FUNCTION_URL}"
echo "  サービスアカウント: ${SCHEDULER_SA}"
echo ""

# ── IAM: Scheduler SA に Cloud Functions 呼び出し権限を付与 ──
echo "[1/4] Cloud Functions Invoker 権限を付与中..."
gcloud functions add-invoker-policy-binding "${FUNCTION_NAME}" \
  --gen2 \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member="serviceAccount:${SCHEDULER_SA}"
echo "      ✓ 権限付与済み"
echo ""

# ── ジョブ登録ヘルパー関数 ────────────────────────────────────
create_or_update_job() {
  local JOB_NAME="$1"
  local SCHEDULE="$2"
  local BODY="$3"
  local DESCRIPTION="$4"

  echo "  ジョブ: ${JOB_NAME}"
  echo "  スケジュール: ${SCHEDULE}（${TIMEZONE}）"
  echo "  ボディ: ${BODY}"

  # 既存ジョブがあれば更新、なければ作成
  if gcloud scheduler jobs describe "${JOB_NAME}" \
      --project="${PROJECT_ID}" \
      --location="${REGION}" &>/dev/null; then
    echo "  → 既存ジョブを更新します"
    gcloud scheduler jobs update http "${JOB_NAME}" \
      --project="${PROJECT_ID}" \
      --location="${REGION}" \
      --schedule="${SCHEDULE}" \
      --uri="${FUNCTION_URL}" \
      --http-method=POST \
      --headers="Content-Type=application/json" \
      --message-body="${BODY}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${FUNCTION_URL}" \
      --time-zone="${TIMEZONE}" \
      --description="${DESCRIPTION}"
  else
    echo "  → 新規ジョブを作成します"
    gcloud scheduler jobs create http "${JOB_NAME}" \
      --project="${PROJECT_ID}" \
      --location="${REGION}" \
      --schedule="${SCHEDULE}" \
      --uri="${FUNCTION_URL}" \
      --http-method=POST \
      --headers="Content-Type=application/json" \
      --message-body="${BODY}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${FUNCTION_URL}" \
      --time-zone="${TIMEZONE}" \
      --description="${DESCRIPTION}"
  fi
  echo "  ✓ 完了"
  echo ""
}

# ── ジョブ1: 週次定期実行（毎週月曜 9:00・一時停止で登録） ──
echo "[2/4] 週次定期実行ジョブを登録中（一時停止状態）..."
create_or_update_job \
  "kintai-weekly-production" \
  "0 9 * * 1" \
  '{"mode":"production"}' \
  "勤怠・工数突き合わせ 週次定期実行（毎週月曜9:00）"

gcloud scheduler jobs pause "kintai-weekly-production" \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
echo "  ✓ kintai-weekly-production を一時停止状態に設定"
echo ""

# ── ジョブ2: 月次確認実行（毎月1日 9:30・一時停止で登録） ───
echo "[3/4] 月次確認実行ジョブを登録中（一時停止状態）..."
create_or_update_job \
  "kintai-monthly-check" \
  "30 9 1 * *" \
  '{"mode":"production","period_days":31}' \
  "勤怠・工数突き合わせ 月次確認実行（毎月1日9:30）"

gcloud scheduler jobs pause "kintai-monthly-check" \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
echo "  ✓ kintai-monthly-check を一時停止状態に設定"
echo ""

# ── ジョブ3: 疎通確認用（手動トリガー専用・一時停止で登録） ─
echo "[4/4] 疎通確認用ジョブを登録中（一時停止状態）..."
create_or_update_job \
  "kintai-test-trigger" \
  "0 12 31 12 *" \
  "{\"mode\":\"test\",\"target_email\":\"y-murakami@use-eng.co.jp\",\"period_days\":7,\"preview\":true}" \
  "疎通確認用（手動トリガー専用。通常は無効）"

gcloud scheduler jobs pause "kintai-test-trigger" \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
echo "  ✓ kintai-test-trigger を一時停止状態に設定"
echo ""

# ── 完了 ──────────────────────────────────────────────────────
echo "======================================================"
echo "  Cloud Scheduler セットアップ完了"
echo "======================================================"
echo ""
echo "  登録済みジョブ一覧（全て PAUSED 状態）:"
gcloud scheduler jobs list \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --format="table(name,schedule,state,lastAttemptTime)"
echo ""
echo "  本番運用開始時は以下で有効化してください:"
echo "    gcloud scheduler jobs resume kintai-weekly-production \\"
echo "      --project=${PROJECT_ID} --location=${REGION}"

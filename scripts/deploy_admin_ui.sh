#!/bin/bash
# ============================================================
# 管理UI デプロイスクリプト（Cloud Run）
# 前提: deploy_cloud_functions.sh 実行済みであること
#
# 使い方:
#   bash scripts/deploy_admin_ui.sh
# ============================================================

set -euo pipefail

# ── 設定 ─────────────────────────────────────────────────────
PROJECT_ID="kintai-kosu-notification"
REGION="asia-northeast1"
SERVICE_NAME="kintai-admin"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
SOURCE_DIR="./admin_ui"

# Cloud Functions の URL（デプロイ後に取得）
FUNCTION_NAME="kintai-reconcile"
FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
  --gen2 \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(serviceConfig.uri)")

# 管理UIパスワードを Secret Manager から取得して確認
echo "ℹ️  admin-ui-password シークレットが必要です。"
echo "   未作成の場合は以下で作成してください:"
echo "   echo -n 'パスワード' | gcloud secrets create admin-ui-password --data-file=- --project=${PROJECT_ID}"
echo ""

# ── ビルド ───────────────────────────────────────────────────
echo "======================================================"
echo "  管理UI デプロイ開始"
echo "======================================================"
echo "  プロジェクト    : ${PROJECT_ID}"
echo "  リージョン      : ${REGION}"
echo "  サービス名      : ${SERVICE_NAME}"
echo "  Cloud Functions : ${FUNCTION_URL}"
echo ""

echo "[1/2] Cloud Build でコンテナイメージをビルド..."
gcloud builds submit "${SOURCE_DIR}" \
  --project="${PROJECT_ID}" \
  --tag="${IMAGE}"

echo ""
echo "[2/2] Cloud Run にデプロイ..."
gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --platform=managed \
  --allow-unauthenticated \
  --memory=256Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=2 \
  --timeout=60s \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},\
CLOUD_FUNCTION_URL=${FUNCTION_URL},\
ADMIN_EMAIL=y-murakami@use-eng.co.jp,\
ADMIN_UI_USER=admin,\
TESTING_MODE=true,\
TZ=Asia/Tokyo"

echo ""
echo "======================================================"
echo "  デプロイ完了"
echo "======================================================"

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(status.url)")

echo ""
echo "  管理UI URL: ${SERVICE_URL}"
echo ""
echo "  ブラウザで開いてください（Basic認証が求められます）:"
echo "    ユーザー名: admin"
echo "    パスワード: Secret Manager の admin-ui-password の値"

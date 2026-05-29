#!/bin/bash
# ============================================================
# Cloud Functions デプロイスクリプト
# 用途: kintai-reconcile 関数のデプロイ
# 実行環境: Cloud Shell または gcloud CLI インストール済み環境
#
# 使い方:
#   bash scripts/deploy_cloud_functions.sh
#   bash scripts/deploy_cloud_functions.sh --allow-unauthenticated  # 開発時
# ============================================================

set -euo pipefail

# ── 設定 ─────────────────────────────────────────────────────
PROJECT_ID="kintai-kosu-notification"
REGION="asia-northeast1"
FUNCTION_NAME="kintai-reconcile"
RUNTIME="python312"
ENTRY_POINT="run"
MEMORY="256Mi"
TIMEOUT="300s"
MAX_INSTANCES="3"
SOURCE_DIR="./cloud_functions"

# テスト期間中の環境変数（本番移行時は OVERRIDE_EMAIL_TO="" / TESTING_MODE=false に変更）
ENV_VARS="TZ=Asia/Tokyo,\
GCP_PROJECT_ID=${PROJECT_ID},\
GCS_BUCKET_NAME=kintai-kosu-sumtime-data,\
SENDER_EMAIL=kintai-notice@use-eng.co.jp,\
ADMIN_EMAIL=y-murakami@use-eng.co.jp,\
OVERRIDE_EMAIL_TO=y-murakami@use-eng.co.jp,\
TESTING_MODE=true"

# ── 引数解析 ─────────────────────────────────────────────────
ALLOW_UNAUTH=""
for arg in "$@"; do
  case $arg in
    --allow-unauthenticated)
      ALLOW_UNAUTH="--allow-unauthenticated"
      echo "⚠️  --allow-unauthenticated が指定されました（開発・テスト用）"
      ;;
  esac
done
AUTH_FLAG="${ALLOW_UNAUTH:---no-allow-unauthenticated}"

# ── デプロイ ─────────────────────────────────────────────────
echo "======================================================"
echo "  Cloud Functions デプロイ開始"
echo "======================================================"
echo "  プロジェクト : ${PROJECT_ID}"
echo "  リージョン   : ${REGION}"
echo "  関数名       : ${FUNCTION_NAME}"
echo "  ランタイム   : ${RUNTIME}"
echo "  メモリ       : ${MEMORY}"
echo "  タイムアウト : ${TIMEOUT}"
echo "  認証         : ${AUTH_FLAG}"
echo ""

gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --runtime="${RUNTIME}" \
  --source="${SOURCE_DIR}" \
  --entry-point="${ENTRY_POINT}" \
  --trigger-http \
  ${AUTH_FLAG} \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --max-instances="${MAX_INSTANCES}" \
  --set-env-vars="${ENV_VARS}"

echo ""
echo "======================================================"
echo "  デプロイ完了"
echo "======================================================"

# デプロイされた関数のURLを取得して表示
FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
  --gen2 \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(serviceConfig.uri)")

echo ""
echo "  関数URL: ${FUNCTION_URL}"
echo ""
echo "  疎通テスト（テストモード）:"
echo "  curl -X POST ${FUNCTION_URL} \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -H 'Authorization: Bearer \$(gcloud auth print-identity-token)' \\"
echo "    -d '{\"mode\":\"test\",\"target_email\":\"y-murakami@use-eng.co.jp\",\"period_days\":7,\"preview\":true}'"

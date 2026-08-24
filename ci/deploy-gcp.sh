#!/usr/bin/env bash
# ForgeGraph — GCP Production Deployment Script
# Usage: bash ci/deploy-gcp.sh [PROJECT_ID] [REGION]
# Requires: gcloud, docker, terraform
set -euo pipefail

PROJECT_ID="${1:-YOUR_GCP_PROJECT_ID}"
REGION="${2:-asia-south1}"
APP_NAME="forgegraph"
IMAGE_TAG="${3:-latest}"

echo "═══════════════════════════════════════════════════"
echo "  ForgeGraph Production Deploy"
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "  Tag:     ${IMAGE_TAG}"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Authenticate ─────────────────────────────────────────────────────
echo ""
echo "1/6 ► Verifying GCP authentication…"
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"
gcloud auth configure-docker "gcr.io" --quiet

# ── Step 2: Build Docker image ───────────────────────────────────────────────
echo ""
echo "2/6 ► Building Docker image…"
IMAGE_URI="gcr.io/${PROJECT_ID}/${APP_NAME}-api:${IMAGE_TAG}"

docker build \
  --platform linux/amd64 \
  --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --build-arg GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
  -t "${IMAGE_URI}" \
  -f Dockerfile \
  .

# ── Step 3: Push to GCR ──────────────────────────────────────────────────────
echo ""
echo "3/6 ► Pushing image to Container Registry…"
docker push "${IMAGE_URI}"
echo "    ✔ Image: ${IMAGE_URI}"

# ── Step 4: Run Alembic migrations ───────────────────────────────────────────
echo ""
echo "4/6 ► Running database migrations…"
# Migrations run as a Cloud Run Job (one-shot)
gcloud run jobs create "${APP_NAME}-migrate-${IMAGE_TAG}" \
  --image "${IMAGE_URI}" \
  --region "${REGION}" \
  --service-account "${APP_NAME}-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-cloudsql-instances "${PROJECT_ID}:${REGION}:${APP_NAME}-db-production" \
  --set-env-vars "STORAGE_BACKEND=postgres,AUTO_CREATE_SCHEMA=false" \
  --set-secrets "DATABASE_PASSWORD=${APP_NAME}-db-password:latest,INTERNAL_WORKER_TOKEN=${APP_NAME}-internal-worker-token:latest" \
  --command "alembic" \
  --args "upgrade,head" \
  --max-retries 1 \
  --quiet 2>/dev/null || echo "    ℹ Migration job already exists, creating new execution…"

gcloud run jobs execute "${APP_NAME}-migrate-${IMAGE_TAG}" \
  --region "${REGION}" \
  --wait
echo "    ✔ Migrations complete"

# ── Step 5: Deploy Cloud Run service ─────────────────────────────────────────
echo ""
echo "5/6 ► Deploying Cloud Run service…"
gcloud run services update "${APP_NAME}-api" \
  --image "${IMAGE_URI}" \
  --region "${REGION}" \
  --quiet

echo "    ✔ Cloud Run deployment started"

# Wait for rollout
gcloud run services describe "${APP_NAME}-api" \
  --region "${REGION}" \
  --format "value(status.url)" > /dev/null

# ── Step 6: Smoke test ───────────────────────────────────────────────────────
echo ""
echo "6/6 ► Running smoke tests…"
API_URL=$(gcloud run services describe "${APP_NAME}-api" \
  --region "${REGION}" \
  --format "value(status.url)")

# Health check
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/health/live")
if [ "${HTTP_STATUS}" = "200" ]; then
  echo "    ✔ /health/live → ${HTTP_STATUS}"
else
  echo "    ✗ /health/live → ${HTTP_STATUS} (FAILED)"
  exit 1
fi

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/health/ready")
if [ "${HTTP_STATUS}" = "200" ]; then
  echo "    ✔ /health/ready → ${HTTP_STATUS}"
else
  echo "    ✗ /health/ready → ${HTTP_STATUS} (WARNING — DB may still be warming up)"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Deployment complete!"
echo "  API URL: ${API_URL}"
echo "  Docs:    ${API_URL}/docs"
echo "═══════════════════════════════════════════════════"

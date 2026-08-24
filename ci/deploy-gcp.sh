#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID to the target project.}"
: "${GCP_REGION:=us-central1}"
: "${FORGEGRAPH_ENVIRONMENT:=staging}"
: "${FORGEGRAPH_BUCKET:?Set FORGEGRAPH_BUCKET to a globally unique private GCS bucket name.}"
: "${TF_VAR_database_password:?Set TF_VAR_database_password in a protected environment.}"
: "${TF_VAR_worker_token:?Set TF_VAR_worker_token in a protected environment.}"

SERVICE="forgegraph-api"
IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/forgegraph/${SERVICE}:${GITHUB_SHA:-$(git rev-parse --short HEAD)}"

 gcloud config set project "$GCP_PROJECT_ID" >/dev/null
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com sqladmin.googleapis.com storage.googleapis.com cloudtasks.googleapis.com secretmanager.googleapis.com

gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev" --quiet
gcloud builds submit --tag "$IMAGE" .

terraform -chdir=infra/gcp init -input=false
terraform -chdir=infra/gcp apply -auto-approve -input=false \
  -var="project_id=${GCP_PROJECT_ID}" \
  -var="region=${GCP_REGION}" \
  -var="environment=${FORGEGRAPH_ENVIRONMENT}" \
  -var="api_image=${IMAGE}" \
  -var="artifact_bucket_name=${FORGEGRAPH_BUCKET}" \
  -var="enable_cloud_tasks=${FORGEGRAPH_ENABLE_CLOUD_TASKS:-false}" \
  -var="cloud_tasks_dispatch_url=${FORGEGRAPH_DISPATCH_URL:-}"

INSTANCE="${GCP_PROJECT_ID}:${GCP_REGION}:forgegraph-${FORGEGRAPH_ENVIRONMENT}"
MIGRATION_JOB="forgegraph-migrate-${FORGEGRAPH_ENVIRONMENT}"
if gcloud run jobs describe "$MIGRATION_JOB" --region "$GCP_REGION" >/dev/null 2>&1; then
  gcloud run jobs update "$MIGRATION_JOB" --image "$IMAGE" --region "$GCP_REGION" \
    --set-cloudsql-instances "$INSTANCE" --command alembic --args upgrade,head
else
  gcloud run jobs create "$MIGRATION_JOB" --image "$IMAGE" --region "$GCP_REGION" \
    --set-cloudsql-instances "$INSTANCE" --command alembic --args upgrade,head
fi
gcloud run jobs execute "$MIGRATION_JOB" --region "$GCP_REGION" --wait

API_URL="$(terraform -chdir=infra/gcp output -raw api_url)"
curl --fail --silent --show-error "${API_URL}/health/live"
printf '\nGCP deployment verified: %s\n' "$API_URL"

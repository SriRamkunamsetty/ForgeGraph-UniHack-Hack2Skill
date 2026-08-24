# ForgeGraph GCP production foundation

This directory defines the production foundation for ForgeGraph on Google Cloud. It provisions a Cloud Run API service, Cloud SQL for PostgreSQL, a private versioned Cloud Storage bucket, Cloud Tasks for retryable catalog processing, Artifact Registry, Secret Manager entries, and least-privilege runtime service accounts.

The API container is intentionally deployed with `AUTO_CREATE_SCHEMA=false`. Database changes must be applied explicitly through Alembic so a new application revision never silently changes the production schema. The Cloud Tasks endpoint is protected by both Cloud Run invocation identity and the `INTERNAL_WORKER_TOKEN` defense-in-depth header.

## Prerequisites

The operator must have a GCP project with billing enabled, Terraform 1.6 or newer, Docker, and authenticated access with permission to enable APIs, create Cloud Run services, create Cloud SQL instances, manage Cloud Storage, create Cloud Tasks queues, create service accounts, and manage Secret Manager. The repository does not contain credentials, passwords, or production state.

## Deployment sequence

Copy `terraform.tfvars.example` to a protected `terraform.tfvars`, replace every placeholder, and never commit the resulting file. Build and push the API image to Artifact Registry before applying Terraform:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/forgegraph/forgegraph-api:$(git rev-parse --short HEAD)"
gcloud auth configure-docker "${REGION}-docker.pkg.dev"
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

Initialize and apply the infrastructure from this directory:

```bash
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
terraform output api_url
```

After the Cloud SQL instance is available, run the schema migration from a controlled runner that can reach the Cloud SQL socket or a configured private connection. For Cloud Run, the recommended approach is a one-off migration job using the same image and runtime service account:

```bash
gcloud run jobs create forgegraph-migrate \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "forgegraph-runtime-staging@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-cloudsql-instances "${PROJECT_ID}:${REGION}:forgegraph-staging" \
  --command alembic --args upgrade,head

gcloud run jobs execute forgegraph-migrate --region "$REGION" --wait
```

For production, use a separate environment suffix, a protected remote Terraform state backend, a controlled approval step, and a migration job tied to the release commit. Verify `/health/live`, `/health/ready`, a catalog upload, a review-task decision, and CSV/XLSX exports before promoting the frontend API URL.

## Configuration boundary

`STORAGE_BACKEND=postgres`, `OBJECT_STORAGE_BACKEND=gcs`, and `JOB_EXECUTION_MODE=cloud_tasks` are production requirements. `AI_PROVIDER=vertex_ai` is enabled only after the project has a reviewed model, budget, data-retention policy, and manufacturer-source governance. `MANUFACTURER_DOMAINS` must contain the approved manufacturer allowlist; an empty allowlist intentionally blocks evidence retrieval.

## Rollback

Cloud Run revision rollback is performed by shifting traffic back to the previous known-good revision. Database migrations must be backward-compatible with both revisions; destructive changes require a separate expand/migrate/contract release sequence. Terraform state must be backed up and protected. Never destroy the production Cloud SQL instance or artifact bucket as part of a normal rollback.

## Safe asynchronous rollout

The first apply should use `enable_cloud_tasks=false` so the API can be migrated and smoke-tested before it starts enqueueing work. After `/health/ready`, a CSV upload, the review API, and both export formats have been verified against Cloud SQL and GCS, set `enable_cloud_tasks=true` and `cloud_tasks_dispatch_url` to the exact URL returned by `terraform output -raw api_url`, then apply again. This avoids creating a queue that points at an unverified or incorrect callback URL.

The same two-step sequence is available through `ci/deploy-gcp.sh`. Set `FORGEGRAPH_ENABLE_CLOUD_TASKS=true` and `FORGEGRAPH_DISPATCH_URL` only for the second rollout. The script does not print database or worker secrets.

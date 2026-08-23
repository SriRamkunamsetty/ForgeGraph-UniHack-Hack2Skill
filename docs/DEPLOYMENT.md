# ForgeGraph Deployment Runbook

ForgeGraph is currently deployed as a permanent public demonstration with a Next.js control tower and a FastAPI catalog-processing API. The two services deploy automatically from the `master` branch of [SriRamkunamsetty/ForgeGraph-UniHack-Hack2Skill](https://github.com/SriRamkunamsetty/ForgeGraph-UniHack-Hack2Skill).

## Production URLs

| Service | URL | Purpose |
|---|---|---|
| Website | https://forgegraph-unihack-hack2skill.vercel.app | Public ForgeGraph control tower for uploading supplier CSV/XLSX files and inspecting catalog quality results |
| API | https://forgegraph-api-root.vercel.app | Public FastAPI service used by the website |
| API health | https://forgegraph-api-root.vercel.app/health/live | Liveness check; returns a JSON status object |
| Repository | https://github.com/SriRamkunamsetty/ForgeGraph-UniHack-Hack2Skill | Source code and deployment configuration |

The repository is currently **public**. The Vercel projects are connected to the GitHub repository and deploy production changes from `master`.

## Deployment topology

The website is a Next.js 14 application in `apps/web`. Its browser-side API base URL is controlled by `NEXT_PUBLIC_API_BASE_URL`; when that variable is absent, the production fallback is `https://forgegraph-api-root.vercel.app`.

The API is a FastAPI application in `apps/api/src/forgegraph`. The repository-root `app.py` is the Vercel entrypoint and imports the application from the API source tree. The root `requirements.txt` contains the runtime dependencies required by the Vercel Python function. The API exposes liveness/readiness checks, catalog job creation, job inspection, quality reporting, product inspection, and CSV export endpoints.

## Required environment variables

### Frontend

`NEXT_PUBLIC_API_BASE_URL` is optional because the repository contains the verified production API fallback. Set it when using a custom API domain or a separate staging backend.

### API

`FORGEGRAPH_CORS_ORIGINS` should include the deployed website origin when the default configuration is replaced. For a custom frontend domain, use a comma-separated list of allowed origins. The reference-pack and data-service variables in `.env.example` are reserved for the persistent production data plane and should not be populated with placeholder credentials.

## Local validation

From the repository root:

```bash
uvicorn forgegraph.main:app --app-dir apps/api/src --host 0.0.0.0 --port 8080
```

In a second terminal:

```bash
cd apps/web
pnpm install
pnpm dev --hostname 0.0.0.0 --port 3000
```

Backend quality gates:

```bash
ruff format --check .
ruff check .
mypy apps/api/src/forgegraph
pytest -q
```

Frontend quality gate:

```bash
cd apps/web
pnpm build
```

## Public smoke tests

```bash
curl --fail https://forgegraph-api-root.vercel.app/health/live
curl --http1.1 --fail \
  -X POST \
  -F 'file=@demo/demo_catalog.csv;type=text/csv' \
  https://forgegraph-api-root.vercel.app/api/v1/catalog/jobs
```

The checked-in demo catalog intentionally contains two resolvable rows and one review-required row. A successful demonstration returns a job with three processed rows, two accepted rows, one review row, and a `waiting_review` status.

## Release and rollback

Push a validated commit to `master` to trigger the connected Vercel production deployments. Confirm that the new frontend and API deployments reach `READY`, then run the health and catalog upload smoke tests above. If a release is faulty, use the Vercel deployment history to promote the last known-good production deployment, or revert the offending commit and push the revert to `master`.

## Current persistence boundary

This deployment is a working end-to-end vertical slice, not yet the complete enterprise data plane. Catalog jobs and derived records currently use the in-memory `CatalogService`, so serverless instance reuse is not a durable persistence guarantee and job state should be treated as demonstration state. The repository includes Docker Compose and schema direction for PostgreSQL/pgvector, Redis, object storage, durable workflow execution, evidence retrieval, and review queues, but those services are not yet wired into the deployed API.

Before using ForgeGraph for operational production data, implement PostgreSQL-backed job and claim persistence, object-storage retention for original files, durable background execution, authentication/RBAC, official UniHack reference-file importing, manufacturer-source retrieval, observability, rate limits, and a retention/deletion policy. Do not use the development starter reference pack as official evaluation ground truth.

## Custom domain

A custom domain can be added to either Vercel project through its Domains settings. After DNS verification, update `NEXT_PUBLIC_API_BASE_URL` if the API domain changes and update `FORGEGRAPH_CORS_ORIGINS` to allow the final website origin. Re-run the public smoke tests after DNS and environment propagation.

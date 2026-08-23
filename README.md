# ForgeGraph

**Evidence-backed product truth for industrial commerce.**

ForgeGraph is the production-grade solution for the UniHack challenge **AI-Powered Product Intelligence for Industrial Commerce**. It transforms sparse supplier spreadsheets and technical documents into structured, validated, explainable, commerce-ready product records.

## Current implementation

The repository currently contains the first end-to-end vertical slice:

- Secure CSV/XLSX upload validation.
- Immutable input SHA-256 hash generation.
- Placeholder and whitespace normalization.
- Manufacturer and brand master-data matching.
- Atomic product claim creation.
- Deterministic validation results.
- Row-level publish/review/blocked status.
- Quality summary and evidence-coverage reporting.
- FastAPI service and an initial Next.js control-tower screen.

The next milestones add the official UniHack reference pack, PostgreSQL persistence, durable workflows, manufacturer-source retrieval, document intelligence, evidence verification, human review, and exact Expected Output export.

## Product architecture

```text
Next.js control tower
        ↓
FastAPI + OpenAPI + Pydantic
        ↓
Durable catalog workflows
        ↓
PostgreSQL + pgvector + object storage + Redis
        ↓
Entity resolution + taxonomy + manufacturer evidence
        ↓
Structured claims + validation firewall
        ↓
Human review or versioned XLSX/CSV/API publication
```

## Local setup

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn forgegraph.main:app --app-dir apps/api/src --reload --port 8080
```

Open the API documentation at `http://localhost:8080/docs` and the health endpoint at `http://localhost:8080/health/live`.

To run the local PostgreSQL and Redis services:

```bash
docker compose up -d postgres redis
```

The first vertical slice uses an isolated in-memory service behind a stable API contract. PostgreSQL migration work will replace this implementation before production publication.

## Frontend setup

```bash
cd apps/web
pnpm install
pnpm dev
```

Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080` for local API access.

## Engineering principles

ForgeGraph separates semantic AI work from deterministic governance. The model proposes structured claims; the validation firewall decides whether those claims are publishable. Unsupported technical values remain unresolved instead of being invented. Every production claim will include provenance, evidence, confidence, rule status, version information, and review history.

## Security principles

Uploaded files and retrieved documents are untrusted. The production system will enforce tenant-aware RBAC, signed object URLs, sandboxed parsing, manufacturer-domain allowlists, strict file and token limits, structured model outputs, SSRF protection, prompt-injection isolation, audit events, secret-manager integration, and release gates.

## Challenge identity

- Team: **Zen Z**
- Team lead: **Mohan Sriram Kunamsetty**
- Challenge: **UniHack 2026 — AI-Powered Product Intelligence for Industrial Commerce**

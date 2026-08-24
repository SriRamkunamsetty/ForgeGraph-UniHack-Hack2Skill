from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import AnyHttpUrl, BaseModel, Field

from forgegraph.ai.extractor import ClaimExtractor
from forgegraph.ai.gateway import StructuredAIGateway
from forgegraph.artifacts.store import build_artifact_store
from forgegraph.catalog.models import CatalogJob, EvidenceSource, HealthResponse, JobResponse
from forgegraph.catalog.service import CatalogService
from forgegraph.core.settings import get_settings
from forgegraph.db.session import Database
from forgegraph.db.store import JobStore, MemoryJobStore, PostgresJobStore
from forgegraph.evidence.retriever import EvidencePolicyError
from forgegraph.evidence.service import EvidenceService
from forgegraph.evidence.store import MemoryEvidenceStore, PostgresEvidenceStore
from forgegraph.observability.audit import AuditService
from forgegraph.observability.metrics import metrics
from forgegraph.review.models import ReviewDecisionRequest, ReviewTaskResponse
from forgegraph.review.service import ReviewService
from forgegraph.review.store import MemoryReviewStore, PostgresReviewStore
from forgegraph.security.auth import authenticate
from forgegraph.workflows.dispatcher import JobDispatcher, build_dispatcher

settings = get_settings()
database: Database | None = None
artifact_store = build_artifact_store(settings)


class EvidenceFetchRequest(BaseModel):
    url: AnyHttpUrl


class ClaimExtractionRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=512)
    category: str = Field(min_length=1, max_length=256)
    allowed_attributes: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)


def build_catalog_service() -> CatalogService:
    global database
    if settings.postgres_enabled:
        database = Database(settings)
        if settings.auto_create_schema:
            database.create_schema()
        store: JobStore = PostgresJobStore(database)
    else:
        store = MemoryJobStore()
    return CatalogService(store=store, artifacts=artifact_store)


catalog_service = build_catalog_service()
if database is not None:
    review_service = ReviewService(PostgresReviewStore(database))
else:
    review_service = ReviewService(MemoryReviewStore())
if database is not None:
    evidence_service = EvidenceService(settings, artifact_store, PostgresEvidenceStore(database))
else:
    evidence_service = EvidenceService(settings, artifact_store, MemoryEvidenceStore())
audit_service = AuditService(database)
dispatcher: JobDispatcher = build_dispatcher(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if database is not None:
        database.engine.dispose()


app = FastAPI(
    title="ForgeGraph API",
    version="0.2.0",
    description="Evidence-backed product intelligence for industrial commerce.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Tenant-ID"],
)


@app.middleware("http")
async def oidc_middleware(request: Request, call_next):
    if settings.auth_enabled and not (
        request.url.path.startswith("/health/")
        or request.url.path.startswith("/internal/")
        or request.url.path == "/docs"
        or request.url.path == "/openapi.json"
    ):
        authenticate(
            request.headers.get("authorization"),
            request.headers.get("x-tenant-id"),
            settings,
        )
    return await call_next(request)


def to_response(job: CatalogJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        status=job.status,
        filename=job.filename,
        input_sha256=job.input_sha256,
        reference_pack_version=job.reference_pack_version,
        quality=job.quality,
        error=job.error,
    )


def tenant_from_header(x_tenant_id: str | None) -> str:
    tenant_id = (x_tenant_id or "local").strip()
    if not tenant_id or len(tenant_id) > 128 or any(char.isspace() for char in tenant_id):
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a non-empty token.")
    return tenant_id


@app.get("/health/live", response_model=HealthResponse, tags=["platform"])
def live_health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.environment)


@app.get("/health/ready", response_model=HealthResponse, tags=["platform"])
def ready_health() -> HealthResponse:
    if database is not None and not database.ping():
        raise HTTPException(status_code=503, detail="Database is not ready.")
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.environment)


@app.post(f"{settings.api_prefix}/catalog/jobs", response_model=JobResponse, tags=["catalog"])
async def create_catalog_job(
    file: Annotated[UploadFile, File(...)],
    reference_pack_version: str = "starter-v0",
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> JobResponse:
    filename = file.filename or "upload.bin"
    extension = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension not in settings.allowed_extension_set:
        raise HTTPException(status_code=415, detail="Only CSV and XLSX uploads are supported.")
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit.")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    tenant_id = tenant_from_header(x_tenant_id)
    try:
        if settings.job_execution_mode == "cloud_tasks":
            job = await asyncio.to_thread(
                catalog_service.create_pending_job,
                filename,
                content,
                reference_pack_version,
                tenant_id,
            )
            await asyncio.to_thread(dispatcher.dispatch, job.id, job.tenant_id)
        else:
            job = await asyncio.to_thread(
                catalog_service.create_job,
                filename,
                content,
                reference_pack_version,
                tenant_id,
            )
            review_service.create_tasks_for_job(job)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit_service.record(tenant_id, "system", "catalog.job.created", "catalog_job", job.id)
    metrics.inc("catalog_job_created")
    return to_response(job)


@app.post("/internal/tasks/catalog", tags=["internal"])
async def process_catalog_task(
    payload: dict[str, str],
    x_forgegraph_worker_token: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    if settings.internal_worker_token and not secrets.compare_digest(
        x_forgegraph_worker_token or "", settings.internal_worker_token
    ):
        raise HTTPException(status_code=401, detail="Invalid worker token.")
    try:
        job_id = UUID(payload["job_id"])
        job = await asyncio.to_thread(catalog_service.process_job, job_id)
        review_service.create_tasks_for_job(job)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid catalog task payload.") from exc
    return {"status": "processed", "job_id": str(job_id)}


@app.get(f"{settings.api_prefix}/catalog/jobs", response_model=list[JobResponse], tags=["catalog"])
def list_catalog_jobs(
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> list[JobResponse]:
    tenant_id = tenant_from_header(x_tenant_id)
    return [to_response(job) for job in catalog_service.list_jobs(tenant_id)]


@app.get(
    f"{settings.api_prefix}/catalog/jobs/{{job_id}}",
    response_model=JobResponse,
    tags=["catalog"],
)
def get_catalog_job(
    job_id: UUID,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> JobResponse:
    job = catalog_service.get_job(job_id)
    if job is None or job.tenant_id != tenant_from_header(x_tenant_id):
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    return to_response(job)


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/products", tags=["catalog"])
def get_catalog_products(
    job_id: UUID,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> list[dict]:
    job = catalog_service.get_job(job_id)
    if job is None or job.tenant_id != tenant_from_header(x_tenant_id):
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    return [product.model_dump(mode="json") for product in job.products]


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/export.csv", tags=["catalog"])
def export_catalog_csv(
    job_id: UUID,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> Response:
    job = catalog_service.get_job(job_id)
    if job is None or job.tenant_id != tenant_from_header(x_tenant_id):
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    try:
        content = catalog_service.export_csv(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Catalog job not found.") from exc
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=forgegraph-{job_id}.csv"},
    )


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/export.xlsx", tags=["catalog"])
def export_catalog_xlsx(
    job_id: UUID,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> Response:
    job = catalog_service.get_job(job_id)
    if job is None or job.tenant_id != tenant_from_header(x_tenant_id):
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    try:
        content = catalog_service.export_xlsx(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Catalog job not found.") from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=forgegraph-{job_id}.xlsx"},
    )


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/quality-report", tags=["catalog"])
def get_quality_report(
    job_id: UUID,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> dict:
    job = catalog_service.get_job(job_id)
    if job is None or job.tenant_id != tenant_from_header(x_tenant_id):
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    return {
        "job_id": str(job.id),
        "status": job.status,
        "quality": job.quality.model_dump(mode="json"),
        "message": (
            "This report is generated from the current vertical slice; "
            "reference-pack validation is being expanded."
        ),
    }


@app.post(
    f"{settings.api_prefix}/evidence/fetch",
    response_model=EvidenceSource,
    tags=["evidence"],
)
async def fetch_evidence(
    request: EvidenceFetchRequest,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> EvidenceSource:
    tenant_id = tenant_from_header(x_tenant_id)
    try:
        source = await asyncio.to_thread(evidence_service.fetch, tenant_id, str(request.url))
        audit_service.record(tenant_id, "system", "evidence.source.fetched", "evidence", source.id)
        metrics.inc("evidence_fetched")
        return source
    except EvidencePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    f"{settings.api_prefix}/catalog/jobs/{{job_id}}/extract-claims",
    tags=["ai"],
)
async def extract_claims(
    job_id: UUID,
    request: ClaimExtractionRequest,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> JobResponse:
    tenant_id = tenant_from_header(x_tenant_id)
    job = catalog_service.get_job(job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    product = next((item for item in job.products if item.product_id == request.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found in catalog job.")
    evidence = [
        source
        for source in evidence_service.list_sources(tenant_id)
        if source.id in set(request.evidence_ids)
    ]
    extractor = ClaimExtractor(StructuredAIGateway(settings))
    claims = await asyncio.to_thread(
        extractor.extract,
        product,
        request.category,
        request.allowed_attributes,
        evidence,
    )
    product.claims.extend(claims)
    product.publish_status = "review_required" if claims else product.publish_status
    updated = catalog_service.recalculate_quality(job)
    review_service.create_tasks_for_job(updated)
    audit_service.record(
        tenant_id,
        "system",
        "claim.extraction.completed",
        "catalog_job",
        job_id,
        {"product_id": request.product_id, "claims_added": len(claims)},
    )
    return to_response(updated)


@app.get(
    f"{settings.api_prefix}/evidence/sources",
    response_model=list[EvidenceSource],
    tags=["evidence"],
)
def list_evidence_sources(
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> list[EvidenceSource]:
    return evidence_service.list_sources(tenant_from_header(x_tenant_id))


@app.get(
    f"{settings.api_prefix}/reviews", response_model=list[ReviewTaskResponse], tags=["reviews"]
)
def list_reviews(
    status: str | None = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> list[ReviewTaskResponse]:
    tenant_id = tenant_from_header(x_tenant_id)
    return [
        ReviewTaskResponse(**task.model_dump())
        for task in review_service.list_tasks(tenant_id, status)
    ]


@app.get(
    f"{settings.api_prefix}/reviews/{{task_id}}",
    response_model=ReviewTaskResponse,
    tags=["reviews"],
)
def get_review(
    task_id: UUID,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> ReviewTaskResponse:
    task = review_service.get_task(task_id, tenant_from_header(x_tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found.")
    return ReviewTaskResponse(**task.model_dump())


@app.post(
    f"{settings.api_prefix}/reviews/{{task_id}}/decision",
    response_model=ReviewTaskResponse,
    tags=["reviews"],
)
def decide_review(
    task_id: UUID,
    request: ReviewDecisionRequest,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_actor: Annotated[str | None, Header()] = None,
) -> ReviewTaskResponse:
    tenant_id = tenant_from_header(x_tenant_id)
    try:
        actor = (x_actor or "local").strip()
        task = review_service.decide(task_id, tenant_id, actor, request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found.")
    audit_service.record(
        tenant_id,
        actor,
        "review.task.decided",
        "review_task",
        task.id,
        {"decision": request.decision.value},
    )
    metrics.inc("review_task_decided")
    return ReviewTaskResponse(**task.model_dump())


@app.get("/metrics", tags=["platform"])
def get_metrics() -> Response:
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


@app.get(f"{settings.api_prefix}/audit", tags=["audit"])
def list_audit_events(
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> list[dict]:
    return audit_service.list(tenant_from_header(x_tenant_id))


def run() -> None:
    import uvicorn

    uvicorn.run(
        "forgegraph.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8080,
        reload=False,
    )

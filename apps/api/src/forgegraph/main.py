from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from forgegraph.catalog.models import CatalogJob, HealthResponse, JobResponse
from forgegraph.catalog.service import CatalogService
from forgegraph.core.settings import get_settings

settings = get_settings()
catalog_service = CatalogService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="ForgeGraph API",
    version="0.1.0",
    description="Evidence-backed product intelligence for industrial commerce.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


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


@app.get("/health/live", response_model=HealthResponse, tags=["platform"])
def live_health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.environment)


@app.get("/health/ready", response_model=HealthResponse, tags=["platform"])
def ready_health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.environment)


@app.post(f"{settings.api_prefix}/catalog/jobs", response_model=JobResponse, tags=["catalog"])
async def create_catalog_job(
    file: Annotated[UploadFile, File(...)],
    reference_pack_version: str = "starter-v0",
) -> JobResponse:
    filename = file.filename or "upload.bin"
    extension = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension not in settings.allowed_extension_set:
        raise HTTPException(status_code=415, detail="Only CSV and XLSX uploads are supported.")
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit.")
    # Keep the first vertical slice responsive while the durable worker is introduced.
    job = await asyncio.to_thread(
        catalog_service.create_job,
        filename,
        content,
        reference_pack_version,
    )
    return to_response(job)


@app.get(
    f"{settings.api_prefix}/catalog/jobs/{{job_id}}",
    response_model=JobResponse,
    tags=["catalog"],
)
def get_catalog_job(job_id: UUID) -> JobResponse:
    job = catalog_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    return to_response(job)


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/products", tags=["catalog"])
def get_catalog_products(job_id: UUID) -> list[dict]:
    job = catalog_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Catalog job not found.")
    return [product.model_dump(mode="json") for product in job.products]


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/export.csv", tags=["catalog"])
def export_catalog_csv(job_id: UUID) -> Response:
    try:
        content = catalog_service.export_csv(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Catalog job not found.") from exc
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=forgegraph-{job_id}.csv"},
    )


@app.get(f"{settings.api_prefix}/catalog/jobs/{{job_id}}/quality-report", tags=["catalog"])
def get_quality_report(job_id: UUID) -> dict:
    job = catalog_service.get_job(job_id)
    if job is None:
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


def run() -> None:
    import uvicorn

    uvicorn.run(
        "forgegraph.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8080,
        reload=False,
    )

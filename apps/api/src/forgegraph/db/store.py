from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from forgegraph.catalog.models import CatalogJob
from forgegraph.db.base import CatalogJobRow
from forgegraph.db.session import Database
from sqlalchemy import select


class JobStore(Protocol):
    def save(self, job: CatalogJob, input_object_key: str | None = None) -> None: ...

    def get(self, job_id: UUID) -> CatalogJob | None: ...

    def list(self, tenant_id: str = "local") -> Iterable[CatalogJob]: ...


class MemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[UUID, CatalogJob] = {}

    def save(self, job: CatalogJob, input_object_key: str | None = None) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: UUID) -> CatalogJob | None:
        return self._jobs.get(job_id)

    def list(self, tenant_id: str = "local") -> Iterable[CatalogJob]:
        return (job for job in self._jobs.values() if job.tenant_id == tenant_id)


class PostgresJobStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, job: CatalogJob, input_object_key: str | None = None) -> None:
        payload = job.model_dump(mode="json")
        with self.database.session_factory() as session:
            row = session.get(CatalogJobRow, job.id)
            if row is None:
                row = CatalogJobRow(
                    id=job.id,
                    tenant_id=job.tenant_id,
                    status=job.status.value,
                    filename=job.filename,
                    input_sha256=job.input_sha256,
                    reference_pack_version=job.reference_pack_version,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    error=job.error,
                    quality_json=payload["quality"],
                    products_json=payload["products"],
                    input_object_key=input_object_key,
                )
                session.add(row)
            else:
                row.tenant_id = job.tenant_id
                row.status = job.status.value
                row.filename = job.filename
                row.input_sha256 = job.input_sha256
                row.reference_pack_version = job.reference_pack_version
                row.updated_at = job.updated_at
                row.error = job.error
                row.quality_json = payload["quality"]
                row.products_json = payload["products"]
                if input_object_key is not None:
                    row.input_object_key = input_object_key
            session.commit()

    def get(self, job_id: UUID) -> CatalogJob | None:
        with self.database.session_factory() as session:
            row = session.scalar(select(CatalogJobRow).where(CatalogJobRow.id == job_id))
            if row is None:
                return None
            return CatalogJob.model_validate(
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "status": row.status,
                    "filename": row.filename,
                    "input_sha256": row.input_sha256,
                    "reference_pack_version": row.reference_pack_version,
                    "created_at": row.created_at or datetime.now(UTC),
                    "updated_at": row.updated_at or datetime.now(UTC),
                    "error": row.error,
                    "quality": row.quality_json,
                    "products": row.products_json,
                    "input_object_key": row.input_object_key,
                }
            )

    def list(self, tenant_id: str = "local") -> Iterable[CatalogJob]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(CatalogJobRow)
                .where(CatalogJobRow.tenant_id == tenant_id)
                .order_by(CatalogJobRow.created_at.desc())
            ).all()
            return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: CatalogJobRow) -> CatalogJob:
        return CatalogJob.model_validate(
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "status": row.status,
                "filename": row.filename,
                "input_sha256": row.input_sha256,
                "reference_pack_version": row.reference_pack_version,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "error": row.error,
                "quality": row.quality_json,
                "products": row.products_json,
                "input_object_key": row.input_object_key,
            }
        )

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from forgegraph.catalog.models import EvidenceSource
from forgegraph.db.base import EvidenceSourceRow
from forgegraph.db.session import Database
from sqlalchemy import select


class MemoryEvidenceStore:
    def __init__(self) -> None:
        self._sources: dict[UUID, EvidenceSource] = {}

    def save(self, tenant_id: str, source: EvidenceSource) -> EvidenceSource:
        self._sources[source.id] = source
        return source

    def list(self, tenant_id: str) -> Iterable[EvidenceSource]:
        return list(self._sources.values())


class PostgresEvidenceStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, tenant_id: str, source: EvidenceSource) -> EvidenceSource:
        with self.database.session_factory() as session:
            row = EvidenceSourceRow(
                id=source.id,
                tenant_id=tenant_id,
                url=source.url,
                source_type=source.source_type,
                title=source.title,
                document_hash=source.document_hash,
                retrieved_at=source.retrieved_at,
                page=source.page,
                evidence_text=source.evidence_text,
                metadata_json={},
            )
            session.merge(row)
            session.commit()
        return source

    def list(self, tenant_id: str) -> Iterable[EvidenceSource]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(EvidenceSourceRow)
                .where(EvidenceSourceRow.tenant_id == tenant_id)
                .order_by(EvidenceSourceRow.retrieved_at.desc())
            ).all()
            return [
                EvidenceSource(
                    id=row.id,
                    url=row.url,
                    source_type=row.source_type,
                    title=row.title,
                    document_hash=row.document_hash,
                    retrieved_at=row.retrieved_at,
                    page=row.page,
                    evidence_text=row.evidence_text,
                )
                for row in rows
            ]

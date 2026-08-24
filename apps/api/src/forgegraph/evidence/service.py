from __future__ import annotations

from typing import Any

from forgegraph.artifacts.store import ArtifactStore
from forgegraph.catalog.models import EvidenceSource
from forgegraph.core.settings import Settings
from forgegraph.evidence.retriever import ManufacturerEvidenceRetriever


class EvidenceService:
    def __init__(self, settings: Settings, artifacts: ArtifactStore, store: Any) -> None:
        self.retriever = ManufacturerEvidenceRetriever(settings)
        self.artifacts = artifacts
        self.store = store

    def fetch(self, tenant_id: str, url: str) -> EvidenceSource:
        document = self.retriever.fetch(url)
        if document.source.document_hash:
            self.artifacts.put(
                f"evidence/{document.source.document_hash}",
                document.content,
                document.content_type,
            )
        save = self.store.save
        return save(tenant_id, document.source)

    def list_sources(self, tenant_id: str) -> list[EvidenceSource]:
        list_sources = self.store.list
        return list(list_sources(tenant_id))

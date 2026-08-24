from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from forgegraph.core.settings import Settings


@dataclass(frozen=True)
class StoredArtifact:
    key: str
    sha256: str
    size_bytes: int
    content_type: str


class ArtifactStore(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> StoredArtifact: ...

    def get(self, key: str) -> bytes: ...


class LocalArtifactStore:
    def __init__(self, root: str | None = None) -> None:
        configured_root = root or os.getenv("FORGEGRAPH_DATA_DIR")
        self.root = (
            Path(configured_root)
            if configured_root
            else Path(tempfile.gettempdir()) / "forgegraph-data"
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, content: bytes, content_type: str) -> StoredArtifact:
        safe_key = key.lstrip("/")
        path = self.root / safe_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredArtifact(
            safe_key, hashlib.sha256(content).hexdigest(), len(content), content_type
        )

    def get(self, key: str) -> bytes:
        return (self.root / key.lstrip("/")).read_bytes()


class GCSArtifactStore:
    def __init__(self, bucket_name: str, project: str | None = None) -> None:
        from google.cloud import storage  # type: ignore[import-not-found]

        self.client = storage.Client(project=project)
        self.bucket = self.client.bucket(bucket_name)

    def put(self, key: str, content: bytes, content_type: str) -> StoredArtifact:
        blob = self.bucket.blob(key.lstrip("/"))
        blob.upload_from_string(content, content_type=content_type)
        return StoredArtifact(key, hashlib.sha256(content).hexdigest(), len(content), content_type)

    def get(self, key: str) -> bytes:
        return self.bucket.blob(key.lstrip("/")).download_as_bytes()


def build_artifact_store(settings: Settings) -> ArtifactStore:
    if settings.gcs_enabled:
        return GCSArtifactStore(settings.object_storage_bucket, settings.gcp_project_id)
    return LocalArtifactStore()

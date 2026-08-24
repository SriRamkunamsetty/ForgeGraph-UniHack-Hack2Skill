from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClaimStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REVIEW_REQUIRED = "review_required"
    UNRESOLVED = "unresolved"
    CONFLICTING = "conflicting"
    REJECTED = "rejected"


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    url: str
    source_type: str = "manufacturer"
    title: str | None = None
    document_hash: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page: int | None = Field(default=None, ge=1)
    evidence_text: str | None = None


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    product_id: str
    attribute: str
    raw_value: str | None = None
    normalized_value: Any = None
    status: ClaimStatus = ClaimStatus.CANDIDATE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[UUID] = Field(default_factory=list)
    source_type: str = "input"
    rule_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    field: str | None = None
    severity: str = "error"
    status: str
    message: str


class ProductRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    mpn: str | None = None
    manufacturer: str | None = None
    brand: str | None = None
    category: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    publish_status: str = "review_required"


class QualitySummary(BaseModel):
    total_rows: int = 0
    processed_rows: int = 0
    accepted_rows: int = 0
    review_rows: int = 0
    failed_rows: int = 0
    claims_total: int = 0
    claims_with_evidence: int = 0
    validation_errors: int = 0
    evidence_coverage: float = 0.0


class CatalogJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "local"
    status: JobStatus = JobStatus.CREATED
    filename: str
    input_sha256: str
    reference_pack_version: str = "starter-v0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    quality: QualitySummary = Field(default_factory=QualitySummary)
    products: list[ProductRecord] = Field(default_factory=list)
    input_object_key: str | None = None


class JobResponse(BaseModel):
    id: UUID
    status: JobStatus
    filename: str
    input_sha256: str
    reference_pack_version: str
    quality: QualitySummary
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str

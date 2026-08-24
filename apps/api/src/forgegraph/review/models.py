from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReviewStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class ReviewTask(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    job_id: UUID
    product_id: str
    risk: float = Field(ge=0.0, le=1.0)
    status: ReviewStatus = ReviewStatus.OPEN
    payload: dict[str, Any] = Field(default_factory=dict)
    assigned_to: str | None = None
    decision: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewDecisionRequest(BaseModel):
    decision: ReviewStatus
    comment: str | None = Field(default=None, max_length=4000)
    edited_values: dict[str, Any] | None = None


class ReviewTaskResponse(ReviewTask):
    pass

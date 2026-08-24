from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from forgegraph.catalog.models import CatalogJob, ProductRecord
from forgegraph.review.models import ReviewDecisionRequest, ReviewStatus, ReviewTask
from forgegraph.review.store import MemoryReviewStore


class ReviewService:
    def __init__(self, store: Any | None = None) -> None:
        self.store = store or MemoryReviewStore()

    def create_tasks_for_job(self, job: CatalogJob) -> list[ReviewTask]:
        existing = {task.product_id for task in self.store.list(job.tenant_id)}
        created: list[ReviewTask] = []
        for product in job.products:
            if product.publish_status == "ready" or product.product_id in existing:
                continue
            task = ReviewTask(
                tenant_id=job.tenant_id,
                job_id=job.id,
                product_id=product.product_id,
                risk=self._risk(product),
                payload=product.model_dump(mode="json"),
            )
            created.append(self.store.save(task))
        return created

    def list_tasks(self, tenant_id: str, status: str | None = None) -> list[ReviewTask]:
        return list(self.store.list(tenant_id, status))

    def get_task(self, task_id: UUID, tenant_id: str) -> ReviewTask | None:
        task = self.store.get(task_id)
        if task is None or task.tenant_id != tenant_id:
            return None
        return task

    def decide(
        self,
        task_id: UUID,
        tenant_id: str,
        actor: str,
        request: ReviewDecisionRequest,
    ) -> ReviewTask | None:
        task = self.get_task(task_id, tenant_id)
        if task is None:
            return None
        if task.status != ReviewStatus.OPEN:
            raise ValueError("Only open review tasks can be decided.")
        if request.decision == ReviewStatus.OPEN:
            raise ValueError("A review decision must approve, reject, or edit the task.")
        task.status = request.decision
        task.decision = {
            "actor": actor,
            "comment": request.comment,
            "edited_values": request.edited_values or {},
            "decided_at": datetime.now(UTC).isoformat(),
        }
        if request.edited_values:
            task.payload = {**task.payload, **request.edited_values}
        task.updated_at = datetime.now(UTC)
        return self.store.save(task)

    @staticmethod
    def _risk(product: ProductRecord) -> float:
        failed_rules = len(product.validations)
        unresolved_claims = sum(
            claim.status.value in {"review_required", "unresolved", "conflicting"}
            for claim in product.claims
        )
        return min(1.0, round(0.25 + failed_rules * 0.1 + unresolved_claims * 0.1, 3))

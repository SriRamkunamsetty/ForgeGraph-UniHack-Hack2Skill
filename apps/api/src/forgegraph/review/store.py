from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from forgegraph.db.base import ReviewTaskRow
from forgegraph.db.session import Database
from forgegraph.review.models import ReviewTask
from sqlalchemy import select


class MemoryReviewStore:
    def __init__(self) -> None:
        self._tasks: dict[UUID, ReviewTask] = {}

    def save(self, task: ReviewTask) -> ReviewTask:
        self._tasks[task.id] = task
        return task

    def get(self, task_id: UUID) -> ReviewTask | None:
        return self._tasks.get(task_id)

    def list(self, tenant_id: str, status: str | None = None) -> Iterable[ReviewTask]:
        tasks = [task for task in self._tasks.values() if task.tenant_id == tenant_id]
        if status:
            tasks = [task for task in tasks if task.status.value == status]
        return sorted(tasks, key=lambda item: item.risk, reverse=True)


class PostgresReviewStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, task: ReviewTask) -> ReviewTask:
        with self.database.session_factory() as session:
            row = session.get(ReviewTaskRow, task.id)
            if row is None:
                row = ReviewTaskRow(
                    id=task.id,
                    tenant_id=task.tenant_id,
                    job_id=task.job_id,
                    product_id=task.product_id,
                    risk=task.risk,
                    status=task.status.value,
                    payload_json=task.payload,
                    assigned_to=task.assigned_to,
                    decision_json=task.decision,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                session.add(row)
            else:
                row.status = task.status.value
                row.risk = task.risk
                row.payload_json = task.payload
                row.assigned_to = task.assigned_to
                row.decision_json = task.decision
                row.updated_at = task.updated_at
            session.commit()
        return task

    def get(self, task_id: UUID) -> ReviewTask | None:
        with self.database.session_factory() as session:
            row = session.get(ReviewTaskRow, task_id)
            if row is None:
                return None
            return self._to_domain(row)

    def list(self, tenant_id: str, status: str | None = None) -> Iterable[ReviewTask]:
        with self.database.session_factory() as session:
            query = select(ReviewTaskRow).where(ReviewTaskRow.tenant_id == tenant_id)
            if status:
                query = query.where(ReviewTaskRow.status == status)
            rows = session.scalars(query.order_by(ReviewTaskRow.risk.desc())).all()
            return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: ReviewTaskRow) -> ReviewTask:
        return ReviewTask.model_validate(
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "job_id": row.job_id,
                "product_id": row.product_id,
                "risk": row.risk,
                "status": row.status,
                "payload": row.payload_json,
                "assigned_to": row.assigned_to,
                "decision": row.decision_json,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

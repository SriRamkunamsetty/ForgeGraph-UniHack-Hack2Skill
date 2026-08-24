from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from forgegraph.db.base import AuditEventRow
from forgegraph.db.session import Database
from sqlalchemy import select


class AuditService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str | UUID,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event_id = uuid4()
        event = {
            "id": str(event_id),
            "tenant_id": tenant_id,
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "payload": payload or {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        if self.database is None:
            self.events.append(event)
            return
        with self.database.session_factory() as session:
            session.add(
                AuditEventRow(
                    id=event_id,
                    tenant_id=tenant_id,
                    actor=actor,
                    action=action,
                    resource_type=resource_type,
                    resource_id=str(resource_id),
                    payload_json=payload or {},
                )
            )
            session.commit()

    def list(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if self.database is None:
            return [event for event in self.events if event["tenant_id"] == tenant_id][-limit:]
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.tenant_id == tenant_id)
                .order_by(AuditEventRow.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": str(row.id),
                    "tenant_id": row.tenant_id,
                    "actor": row.actor,
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "payload": row.payload_json,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

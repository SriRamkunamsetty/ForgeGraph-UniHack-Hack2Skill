"""create forgegraph durable core tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    op.create_table(
        "catalog_jobs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("reference_pack_version", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("quality_json", jsonb, nullable=False),
        sa.Column("products_json", jsonb, nullable=False),
        sa.Column("input_object_key", sa.String(length=1024), nullable=True),
    )
    op.create_index("ix_catalog_jobs_tenant_id", "catalog_jobs", ["tenant_id"])
    op.create_index("ix_catalog_jobs_status", "catalog_jobs", ["status"])
    op.create_index("ix_catalog_jobs_input_sha256", "catalog_jobs", ["input_sha256"])

    op.create_table(
        "evidence_sources",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("document_hash", sa.String(length=64), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", jsonb, nullable=False),
    )
    op.create_index("ix_evidence_sources_tenant_id", "evidence_sources", ["tenant_id"])

    op.create_table(
        "review_tasks",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", uuid, nullable=False),
        sa.Column("product_id", sa.String(length=512), nullable=False),
        sa.Column("risk", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", jsonb, nullable=False),
        sa.Column("assigned_to", sa.String(length=256), nullable=True),
        sa.Column("decision_json", jsonb, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_tasks_tenant_id", "review_tasks", ["tenant_id"])
    op.create_index("ix_review_tasks_job_id", "review_tasks", ["job_id"])
    op.create_index("ix_review_tasks_product_id", "review_tasks", ["product_id"])
    op.create_index("ix_review_tasks_status", "review_tasks", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=False),
        sa.Column("payload_json", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("review_tasks")
    op.drop_table("evidence_sources")
    op.drop_table("catalog_jobs")

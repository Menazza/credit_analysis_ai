"""Add mapping_rules, unmapped_labels, pipeline_runs, version tracking

Revision ID: 006
Revises: 005
Create Date: 2026-02-24

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mapping_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(50), nullable=False, server_default="global"),
        sa.Column("scope_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_expense", sa.Boolean(), server_default="false"),
    )
    op.create_index("ix_mapping_rules_tenant_scope", "mapping_rules", ["tenant_id", "scope"])
    op.create_index("ix_mapping_rules_pattern", "mapping_rules", ["pattern"])

    op.create_table(
        "unmapped_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("raw_label", sa.String(500), nullable=False),
        sa.Column("sheet", sa.String(100), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), server_default="1"),
    )
    op.create_index("ix_unmapped_labels_tenant", "unmapped_labels", ["tenant_id"])
    op.create_index("ix_unmapped_labels_raw_label", "unmapped_labels", ["raw_label"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("credit_review_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_review_versions.id"), nullable=True),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("artifact_ids_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("counts_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("ix_pipeline_runs_input_hash", "pipeline_runs", ["input_hash", "stage"])
    op.create_index("ix_pipeline_runs_version_stage", "pipeline_runs", ["credit_review_version_id", "stage"])


def downgrade() -> None:
    op.drop_table("pipeline_runs")
    op.drop_table("unmapped_labels")
    op.drop_table("mapping_rules")

"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("settings_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("status", sa.String(50), server_default="ACTIVE"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
    )
    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id"), nullable=False),
    )
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("reg_no", sa.String(100)),
        sa.Column("country", sa.String(2)),
        sa.Column("sector", sa.String(100)),
        sa.Column("is_listed", sa.String(10), server_default="false"),
        sa.Column("ticker", sa.String(20)),
        sa.Column("group_structure_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
    )
    op.create_table(
        "portfolio_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
    )
    op.create_table(
        "engagements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="ACTIVE"),
    )
    op.create_table(
        "credit_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id"), nullable=False),
        sa.Column("review_period_end", sa.Date()),
        sa.Column("base_currency", sa.String(3), server_default="ZAR"),
        sa.Column("status", sa.String(50), server_default="DRAFT"),
    )
    op.create_table(
        "credit_review_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("credit_review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_reviews.id"), nullable=False),
        sa.Column("version_no", sa.String(20), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("locked_at", sa.Date()),
        sa.Column("lock_reason", sa.String(500)),
    )
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        # Optional engagement context so docs are scoped to a specific review
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id")),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("storage_url", sa.String(1000)),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("parser_version", sa.String(50)),
        sa.Column("status", sa.String(50), server_default="PENDING"),
    )
    op.create_table(
        "page_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.String(1000)),
        sa.Column("tokens_json_url", sa.String(1000)),
        sa.Column("text_hash", sa.String(64)),
    )
    op.create_table(
        "page_layouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("page_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("page_assets.id"), nullable=False),
        sa.Column("regions_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_table(
        "presentation_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("scope", sa.String(50), nullable=False),
        sa.Column("scope_key", sa.String(100)),
        sa.Column("currency", sa.String(3)),
        sa.Column("scale", sa.String(50)),
        sa.Column("scale_factor", sa.Float()),
        sa.Column("period_weeks", sa.Integer()),
        sa.Column("evidence_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("statement_type", sa.String(20), nullable=False),
        sa.Column("entity_scope", sa.String(20), server_default="GROUP"),
        sa.Column("periods_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_table(
        "statement_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("statements.id"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("raw_label", sa.String(500), nullable=False),
        sa.Column("section_path", sa.String(200)),
        sa.Column("note_refs_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("values_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("evidence_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "notes_index",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("note_number", sa.String(20)),
        sa.Column("title", sa.String(500)),
        sa.Column("start_page", sa.Integer()),
        sa.Column("end_page", sa.Integer()),
        sa.Column("confidence", sa.Float()),
    )
    op.create_table(
        "note_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("note_number", sa.String(20)),
        sa.Column("title", sa.String(500)),
        sa.Column("blocks_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("tables_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("presentation_context_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("presentation_contexts.id")),
        sa.Column("evidence_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "canonical_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("canonical_key", sa.String(100), nullable=False),
        sa.Column("statement_type", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(200)),
        sa.Column("description", sa.String(500)),
        sa.Column("allow_negative", sa.String(10), server_default="true"),
        sa.Column("tags_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_index("ix_canonical_accounts_canonical_key", "canonical_accounts", ["canonical_key"], unique=True)
    op.create_table(
        "mapping_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("raw_label_hash", sa.String(64), nullable=False),
        sa.Column("raw_label", sa.String(500), nullable=False),
        sa.Column("statement_type", sa.String(20), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("method", sa.String(20), server_default="LLM"),
        sa.Column("rationale", sa.String(500)),
        sa.Column("evidence_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "validation_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("checks_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("failures_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_table(
        "normalized_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("statement_type", sa.String(20), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=False),
        sa.Column("value_base", sa.Float(), nullable=False),
        sa.Column("value_original", sa.Float()),
        sa.Column("unit_meta_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("source_refs_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_table(
        "facilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("lender", sa.String(255)),
        sa.Column("facility_type", sa.String(100)),
        sa.Column("limit", sa.Float()),
        sa.Column("utilisation", sa.Float()),
        sa.Column("currency", sa.String(3)),
        sa.Column("pricing_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("maturity_date", sa.Date()),
        sa.Column("amort_profile_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("status", sa.String(50), server_default="ACTIVE"),
    )
    op.create_table(
        "security_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("security_type", sa.String(100)),
        sa.Column("description", sa.String(1000)),
        sa.Column("value_estimate", sa.Float()),
        sa.Column("ranking", sa.String(50)),
        sa.Column("evidence_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "covenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("definition_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("threshold_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("testing_frequency", sa.String(50)),
        sa.Column("notes", sa.String(500)),
    )
    op.create_table(
        "covenant_tests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("covenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("covenants.id"), nullable=False),
        sa.Column("test_date", sa.Date(), nullable=False),
        sa.Column("actual_value", sa.Float()),
        sa.Column("threshold", sa.Float()),
        sa.Column("headroom", sa.Float()),
        sa.Column("status", sa.String(20)),
        sa.Column("evidence_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "rating_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "metric_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("credit_review_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_review_versions.id"), nullable=False),
        sa.Column("metric_key", sa.String(100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("period_end", sa.Date()),
        sa.Column("calc_trace_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_table(
        "rating_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("credit_review_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_review_versions.id"), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rating_models.id"), nullable=False),
        sa.Column("rating_grade", sa.String(20)),
        sa.Column("pd_band", sa.Float()),
        sa.Column("score_breakdown_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("overrides_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("rationale_json", postgresql.JSONB(), server_default="{}"),
    )
    op.create_table(
        "commentary_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("credit_review_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_review_versions.id"), nullable=False),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("text", sa.String(10000)),
        sa.Column("sources_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("generated_by", sa.String(20), server_default="MANUAL"),
        sa.Column("locked", sa.String(10), server_default="false"),
    )
    op.create_table(
        "export_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("credit_review_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_review_versions.id"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("storage_url", sa.String(1000)),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("diff_json", postgresql.JSONB(), server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("export_artifacts")
    op.drop_table("commentary_blocks")
    op.drop_table("rating_results")
    op.drop_table("metric_facts")
    op.drop_table("rating_models")
    op.drop_table("covenant_tests")
    op.drop_table("covenants")
    op.drop_table("security_items")
    op.drop_table("facilities")
    op.drop_table("normalized_facts")
    op.drop_table("validation_reports")
    op.drop_table("mapping_decisions")
    op.drop_index("ix_canonical_accounts_canonical_key", table_name="canonical_accounts")
    op.drop_table("canonical_accounts")
    op.drop_table("note_extractions")
    op.drop_table("notes_index")
    op.drop_table("statement_lines")
    op.drop_table("statements")
    op.drop_table("presentation_contexts")
    op.drop_table("page_layouts")
    op.drop_table("page_assets")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("credit_review_versions")
    op.drop_table("credit_reviews")
    op.drop_table("engagements")
    op.drop_table("portfolio_companies")
    op.drop_table("portfolios")
    op.drop_table("companies")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")

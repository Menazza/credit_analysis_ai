"""Add note_chunks table for on-demand notes retrieval

Revision ID: 004
Revises: 003
Create Date: 2026-02-20

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "note_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),  # GROUP, COMPANY
        sa.Column("note_id", sa.String(50), nullable=False),  # e.g. GROUP:21
        sa.Column("chunk_id", sa.String(80), nullable=False),  # e.g. GROUP:21.1
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("tables_json", postgresql.JSONB(), server_default="[]"),
        sa.Column("tokens_approx", sa.Integer(), nullable=True),
        sa.Column("keywords_json", postgresql.JSONB(), server_default="[]"),
    )
    op.create_index("ix_note_chunks_doc_scope", "note_chunks", ["document_version_id", "scope"])
    op.create_index("ix_note_chunks_note_id", "note_chunks", ["document_version_id", "note_id"])


def downgrade() -> None:
    op.drop_index("ix_note_chunks_note_id", table_name="note_chunks")
    op.drop_index("ix_note_chunks_doc_scope", table_name="note_chunks")
    op.drop_table("note_chunks")

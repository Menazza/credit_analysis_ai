"""Add tsvector and embedding columns for hybrid notes search

Revision ID: 005
Revises: 004
Create Date: 2026-02-20

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector (Neon supports it; harmless if already enabled)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # GIN index for full-text search (tsvector) - index on expression, no stored column
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_note_chunks_search_vector ON note_chunks
        USING GIN(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(text, '')))
    """)

    # Add vector column for embeddings (1536 dims for text-embedding-3-small)
    op.execute("""
        ALTER TABLE note_chunks ADD COLUMN IF NOT EXISTS embedding vector(1536)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_note_chunks_search_vector")
    op.execute("ALTER TABLE note_chunks DROP COLUMN IF EXISTS embedding")

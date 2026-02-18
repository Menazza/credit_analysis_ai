"""Add engagement_id to documents

Revision ID: 002
Revises: 001
Create Date: 2026-02-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add optional engagement_id FK to documents to scope docs to engagements."""
    # Add column as nullable so existing rows are valid
    op.add_column(
        "documents",
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove engagement_id from documents."""
    op.drop_column("documents", "engagement_id")


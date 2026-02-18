"""
Audit logging — who uploaded what, which version produced which outputs.
Every mapping and override recorded. Immutable audit trail.
"""
from uuid import UUID
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.audit import AuditLog


async def log_action(
    db: AsyncSession,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    diff: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        diff_json=diff or {},
    )
    db.add(entry)
    await db.flush()

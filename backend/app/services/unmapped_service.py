"""
Track 3A: Unmapped queue — aggregate by frequency, top unmapped, create global rule vs document override.
"""
from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mapping import MappingDecision
from app.models.mapping_rule import MappingRule, UnmappedLabel
from app.services.extraction_loader import load_extraction_from_s3, extraction_to_flat_rows
from app.services.mapping_rules import map_raw_label


def get_unmapped_from_extraction(extraction: dict, limit: int = 100) -> list[dict[str, Any]]:
    """Derive unmapped labels from extraction dict. Returns list of {raw_label, count, sheets}."""
    sheet_to_type = {s: s.split("_")[0] for s in extraction.keys()}
    flat = extraction_to_flat_rows(extraction, sheet_to_type)
    raw_with_sheet = [(r.get("raw_label", ""), r.get("sheet", "")) for r in flat if r.get("raw_label")]
    counter: Counter[tuple[str, str]] = Counter(raw_with_sheet)
    unmapped_set: dict[str, dict] = {}
    for (raw, sheet), cnt in counter.most_common(limit * 2):
        if not raw:
            continue
        key, _, _ = map_raw_label(raw)
        if key:
            continue
        if raw not in unmapped_set:
            unmapped_set[raw] = {"raw_label": raw, "count": 0, "sheets": set()}
        unmapped_set[raw]["count"] += cnt
        if sheet:
            unmapped_set[raw]["sheets"].add(sheet)
    result = [
        {"raw_label": v["raw_label"], "count": v["count"], "sheets": list(v["sheets"])[:5]}
        for v in sorted(unmapped_set.values(), key=lambda x: -x["count"])
    ]
    return result[:limit]


async def get_top_unmapped_aggregate(
    db: AsyncSession,
    tenant_id: UUID,
    document_version_ids: list[UUID] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Aggregate unmapped labels by frequency across document versions.
    If document_version_ids given, scope to those; else use UnmappedLabel table for tenant.
    """
    if document_version_ids:
        q = (
            select(UnmappedLabel.raw_label, func.sum(UnmappedLabel.occurrence_count).label("total"))
            .where(
                UnmappedLabel.tenant_id == tenant_id,
                UnmappedLabel.document_version_id.in_(document_version_ids),
            )
            .group_by(UnmappedLabel.raw_label)
            .order_by(func.sum(UnmappedLabel.occurrence_count).desc())
            .limit(limit)
        )
        rows = (await db.execute(q)).all()
        return [{"raw_label": r.raw_label, "count": int(r.total)} for r in rows]
    q = (
        select(UnmappedLabel.raw_label, func.sum(UnmappedLabel.occurrence_count).label("total"))
        .where(UnmappedLabel.tenant_id == tenant_id)
        .group_by(UnmappedLabel.raw_label)
        .order_by(func.sum(UnmappedLabel.occurrence_count).desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    return [{"raw_label": r.raw_label, "count": int(r.total)} for r in rows]


async def create_mapping_rule(
    db: AsyncSession,
    tenant_id: UUID,
    pattern: str,
    canonical_key: str,
    is_expense: bool = False,
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Create a global MappingRule. Used when user chooses 'create global rule' for unmapped label."""
    rule = MappingRule(
        tenant_id=tenant_id,
        pattern=pattern.strip().lower(),
        canonical_key=canonical_key,
        scope="global",
        priority=50,
        is_expense=is_expense,
        created_by=created_by,
    )
    db.add(rule)
    await db.flush()
    return {"id": str(rule.id), "pattern": rule.pattern, "canonical_key": rule.canonical_key, "scope": "global"}


async def upsert_unmapped_labels(
    db: AsyncSession,
    tenant_id: UUID,
    document_version_id: UUID,
    unmapped: list[dict[str, Any]],
) -> None:
    """Upsert unmapped labels for a document version (from mapping pipeline output)."""
    await db.execute(delete(UnmappedLabel).where(UnmappedLabel.document_version_id == document_version_id))
    for u in unmapped:
        db.add(UnmappedLabel(
            tenant_id=tenant_id,
            document_version_id=document_version_id,
            raw_label=u.get("raw_label", "")[:500],
            sheet=u.get("sheet"),
            occurrence_count=u.get("count", 1),
        ))
    await db.flush()

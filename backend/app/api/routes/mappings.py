"""
Phase 3: API for mapping review and manual override.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User
from app.models.company import CreditReview, CreditReviewVersion, Engagement
from app.services.extraction_loader import load_extraction_from_s3, extraction_to_flat_rows
from app.services.llm_mapping_suggestions import suggest_canonical_key, suggest_batch

router = APIRouter(prefix="/mappings", tags=["mappings"])


class MappingSuggestionResponse(BaseModel):
    raw_label: str
    canonical_key: str | None
    confidence: float
    rationale: str
    method: str


@router.get("/suggest", response_model=MappingSuggestionResponse)
async def get_mapping_suggestion(
    raw_label: str = Query(..., min_length=1),
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get LLM/rule-based suggestion for mapping raw_label to canonical_key."""
    result = suggest_canonical_key(raw_label)
    return MappingSuggestionResponse(
        raw_label=raw_label,
        canonical_key=result.get("canonical_key"),
        confidence=result.get("confidence", 0),
        rationale=result.get("rationale", ""),
        method=result.get("method", "UNMAPPED"),
    )


@router.get("/unmapped")
async def list_unmapped_labels(
    document_version_id: UUID | None = None,
    document_version_ids: str | None = Query(None, description="Comma-separated IDs for aggregation"),
    top: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List raw labels that did not map. Single document_version_id: from extraction.
    document_version_ids (comma-separated): aggregate top unmapped across versions from DB.
    """
    from app.services.unmapped_service import get_top_unmapped_aggregate, get_unmapped_from_extraction
    from app.models.document import DocumentVersion, Document
    from sqlalchemy import select

    if document_version_ids:
        ids = [UUID(x.strip()) for x in document_version_ids.split(",") if x.strip()]
        rows = await get_top_unmapped_aggregate(db, user.tenant_id, document_version_ids=ids, limit=top)
        return {"unmapped": [r["raw_label"] for r in rows], "top_with_counts": rows}
    if document_version_id:
        result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == document_version_id,
                DocumentVersion.document_id.in_(
                    select(Document.id).where(Document.tenant_id == user.tenant_id)
                ),
            )
        )
        dv = result.scalar_one_or_none()
        if not dv or dv.status != "MAPPED":
            raise HTTPException(status_code=404, detail="Document version not found or not extracted")
        doc_result = await db.execute(select(Document).where(Document.id == dv.document_id))
        doc = doc_result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        pdf_name = (doc.original_filename or "document").replace(".pdf", "").replace(".PDF", "")
        excel_key = f"extracted/{doc.tenant_id}/{dv.id}/statements_{pdf_name}.xlsx"
        try:
            extraction = load_extraction_from_s3(excel_key)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not load extraction: {e}")
        rows = get_unmapped_from_extraction(extraction, limit=top)
        unmapped = [r["raw_label"] for r in rows]
        return {"unmapped": unmapped, "top_with_counts": rows}
    raise HTTPException(status_code=400, detail="Provide document_version_id or document_version_ids")


class ManualOverrideRequest(BaseModel):
    raw_label: str
    canonical_key: str


class CreateGlobalRuleRequest(BaseModel):
    raw_label: str
    canonical_key: str
    is_expense: bool = False


@router.post("/rule")
async def create_global_rule(
    data: CreateGlobalRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a global mapping rule (Track 3A). Future mapping runs use this."""
    from app.services.unmapped_service import create_mapping_rule
    rule = await create_mapping_rule(
        db, user.tenant_id, data.raw_label.strip().lower(), data.canonical_key,
        is_expense=data.is_expense, created_by=user.id,
    )
    await db.commit()
    return rule


@router.post("/override")
async def create_manual_override(
    data: ManualOverrideRequest,
    document_version_id: UUID | None = None,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Record manual mapping. document_version_id: override for this doc only; else tenant-wide."""
    import hashlib
    from app.models.mapping import MappingDecision
    from app.models.mapping_rule import MappingRule

    if document_version_id:
        rule = MappingRule(
            tenant_id=user.tenant_id,
            pattern=data.raw_label.strip().lower(),
            canonical_key=data.canonical_key,
            scope="per_document_version",
            scope_entity_id=document_version_id,
            priority=80,
            created_by=user.id,
        )
        db.add(rule)
        await db.flush()
        await db.commit()
        return {"id": str(rule.id), "raw_label": data.raw_label, "canonical_key": data.canonical_key, "scope": "per_document_version"}

    raw_label_hash = hashlib.sha256(data.raw_label.encode("utf-8")).hexdigest()
    md = MappingDecision(
        tenant_id=user.tenant_id,
        raw_label_hash=raw_label_hash,
        raw_label=data.raw_label,
        statement_type="SCI",  # Generic; could be inferred
        canonical_key=data.canonical_key,
        confidence=1.0,
        method="MANUAL",
        rationale="Manual override via API",
    )
    db.add(md)
    await db.flush()
    await db.commit()
    return {"id": str(md.id), "raw_label": data.raw_label, "canonical_key": data.canonical_key}

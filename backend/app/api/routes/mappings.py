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
    document_version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List raw labels from extraction that did not map to a canonical key.
    For mapping review UI.
    """
    from sqlalchemy import select
    from app.models.document import DocumentVersion, Document

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

    from app.services.mapping_rules import map_raw_label

    sheet_to_type = {s: s.split("_")[0] for s in extraction.keys()}
    flat = extraction_to_flat_rows(extraction, sheet_to_type)
    raw_labels = sorted(set(r["raw_label"] for r in flat if r.get("raw_label")))
    unmapped = [r for r in raw_labels if not map_raw_label(r)[0]]

    return {"unmapped": unmapped, "total_raw": len(raw_labels)}


class ManualOverrideRequest(BaseModel):
    raw_label: str
    canonical_key: str


@router.post("/override")
async def create_manual_override(
    data: ManualOverrideRequest,
    document_version_id: UUID | None = None,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Record a manual mapping decision for review/audit.
    Persists to MappingDecision; future mapping runs can use tenant overrides.
    """
    import hashlib
    from app.models.mapping import MappingDecision

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
    return {"id": str(md.id), "raw_label": data.raw_label, "canonical_key": data.canonical_key}

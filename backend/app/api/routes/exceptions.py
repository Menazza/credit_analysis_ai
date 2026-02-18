"""
Exception queue — human-in-the-loop: failed tie-outs, unknown scale, unmapped lines.
Reviewer UI can approve mappings, fix labels, adjust scale.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User
from app.models.mapping import ValidationReport
from app.models.document import DocumentVersion

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.get("/queue")
async def list_exception_queue(
    status: str | None = Query(None, description="PASS, FAIL, WARN"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List validation reports that need human review (FAIL or WARN)."""
    from app.models.document import Document
    q = (
        select(ValidationReport)
        .join(DocumentVersion, DocumentVersion.id == ValidationReport.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.tenant_id == user.tenant_id)
    )
    if status:
        q = q.where(ValidationReport.status == status)
    result = await db.execute(q)
    rows = result.scalars().all()
    return {
        "items": [
            {
                "document_version_id": str(r.document_version_id),
                "status": r.status,
                "failures": r.failures_json,
            }
            for r in rows
        ],
    }


@router.post("/mapping/approve")
async def approve_mapping(
    raw_label_hash: str,
    canonical_key: str,
    statement_type: str,
    user: User = Depends(get_current_user),
):
    """Approve or override a mapping decision. Full impl would upsert MappingDecision with method=MANUAL."""
    return {"message": "Mapping approval would persist to mapping_decisions.", "canonical_key": canonical_key}

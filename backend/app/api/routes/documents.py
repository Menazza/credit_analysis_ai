import hashlib
import io
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User
from app.models.company import Company
from app.models.document import Document, DocumentVersion
from app.models.extraction import PresentationContext, Statement, NotesIndex, NoteExtraction
from app.services.storage import upload_file, generate_doc_key, download_file_from_url
from app.services.statements_export import (
    build_statements_xlsx,
    build_statements_csv,
    build_mappings_xlsx,
    build_mappings_csv,
)
from app.worker.tasks import run_ingest_pipeline

router = APIRouter(prefix="/documents", tags=["documents"])

DOC_TYPES = [
    "AFS",
    "MA",
    "TB",
    "DEBT_SCHEDULE",
    "COV_CERT",
    "FORECAST",
    "TERM_SHEET",
    "BANK_STATEMENT",
    "OTHER",
]


class DocumentResponse(BaseModel):
    id: str
    company_id: str
    doc_type: str
    original_filename: str
    storage_url: str | None
    uploaded_at: str | None
    latest_version_id: str | None = None

    class Config:
        from_attributes = True


class DocumentVersionResponse(BaseModel):
    id: str
    document_id: str
    status: str
    sha256: str | None
    created_at: str | None

    class Config:
        from_attributes = True


class DocumentVersionSummaryResponse(BaseModel):
    id: str
    document_id: str
    status: str
    sha256: str | None
    created_at: str | None
    doc_type: str
    original_filename: str
    # Raw LLM/semantic outputs so the UI can inspect what was mapped
    presentation_scale: dict | None = None
    canonical_mappings: dict | None = None
    note_classifications: dict | None = None
    notes_index: list[dict] | None = None
    note_extractions: list[dict] | None = None
    reconciliation_checks: dict | None = None


class LlmInputDebugResponse(BaseModel):
    id: str
    document_id: str
    pages: list[dict]


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    company_id: UUID,
    doc_type: str | None = None,
    engagement_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Document).where(
        Document.company_id == company_id,
        Document.tenant_id == user.tenant_id,
    )
    if engagement_id:
        q = q.where(Document.engagement_id == engagement_id)
    if doc_type:
        q = q.where(Document.doc_type == doc_type)
    result = await db.execute(q)
    docs = result.scalars().all()

    responses: list[DocumentResponse] = []
    for d in docs:
        # Fetch latest version for this document (if any) so UI can link to analysis
        v_result = await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == d.id)
            .order_by(DocumentVersion.created_at.desc())
        )
        v = v_result.scalars().first()
        responses.append(
            DocumentResponse(
                id=str(d.id),
                company_id=str(d.company_id),
                doc_type=d.doc_type,
                original_filename=d.original_filename,
                storage_url=d.storage_url,
                uploaded_at=d.created_at.isoformat() if d.created_at else None,
                latest_version_id=str(v.id) if v else None,
            )
        )

    return responses


@router.post("/upload", response_model=DocumentVersionResponse)
async def upload_document(
    company_id: UUID = Form(...),
    doc_type: str = Form(...),
    engagement_id: UUID | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"doc_type must be one of {DOC_TYPES}")
    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")

    if engagement_id:
        # Ensure engagement belongs to same tenant & company
        from app.models.company import Engagement  # local import to avoid circular import at startup

        eng_result = await db.execute(
            select(Engagement).where(
                Engagement.id == engagement_id,
                Engagement.company_id == company_id,
                Engagement.tenant_id == user.tenant_id,
            )
        )
        if not eng_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Engagement not found for this company")

    content = await file.read()
    sha256 = hashlib.sha256(content).hexdigest()
    filename = file.filename or "upload.bin"

    doc = Document(
        tenant_id=user.tenant_id,
        company_id=company_id,
        engagement_id=engagement_id,
        doc_type=doc_type,
        original_filename=filename,
        uploaded_by=user.id,
    )
    db.add(doc)
    await db.flush()

    key = generate_doc_key(str(user.tenant_id), str(company_id), str(doc.id), filename)
    url = upload_file(key, io.BytesIO(content), content_type=file.content_type or "application/pdf")
    doc.storage_url = url
    await db.flush()

    version = DocumentVersion(
        document_id=doc.id,
        sha256=sha256,
        status="PENDING",
    )
    db.add(version)
    await db.flush()

    run_ingest_pipeline.delay(str(version.id))
    return DocumentVersionResponse(
        id=str(version.id),
        document_id=str(version.document_id),
        status=version.status,
        sha256=version.sha256,
        created_at=version.created_at.isoformat() if version.created_at else None,
    )


@router.get("/versions/{version_id}", response_model=DocumentVersionResponse)
async def get_document_version(
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == version_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return DocumentVersionResponse(
        id=str(v.id),
        document_id=str(v.document_id),
        status=v.status,
        sha256=v.sha256,
        created_at=v.created_at.isoformat() if v.created_at else None,
    )


@router.get("/versions/{version_id}/summary", response_model=DocumentVersionSummaryResponse)
async def get_document_version_summary(
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    High-level semantic summary for a specific uploaded document version.

    Surfaces:
    - basic version + document metadata
    - presentation scale (currency/units)
    - canonical mappings (raw labels → canonical keys)
    - note classifications
    so that users can inspect what the extraction/mapping pipeline produced.
    """
    # Ensure version belongs to current tenant
    result = await db.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == version_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    version, doc = row

    ctx_result = await db.execute(
        select(PresentationContext).where(PresentationContext.document_version_id == version.id)
    )
    contexts = ctx_result.scalars().all()

    pres_scale = None
    mappings = None
    notes = None
    for ctx in contexts:
        if ctx.scope == "DOC" and ctx.scope_key == "presentation_scale":
            pres_scale = ctx.evidence_json
        elif ctx.scope == "DOC" and ctx.scope_key == "canonical_mappings":
            mappings = ctx.evidence_json
        elif ctx.scope == "DOC" and ctx.scope_key == "note_classifications":
            notes = ctx.evidence_json

    recon_ctx_result = await db.execute(
        select(PresentationContext).where(
            PresentationContext.document_version_id == version.id,
            PresentationContext.scope == "DOC",
            PresentationContext.scope_key == "reconciliation_checks",
        )
    )
    recon_ctx = recon_ctx_result.scalars().first()
    reconciliation_checks = recon_ctx.evidence_json if recon_ctx and recon_ctx.evidence_json else None

    ni_result = await db.execute(
        select(NotesIndex).where(NotesIndex.document_version_id == version.id)
    )
    notes_index_rows = ni_result.scalars().all()
    ne_result = await db.execute(
        select(NoteExtraction).where(NoteExtraction.document_version_id == version.id)
    )
    note_extraction_rows = ne_result.scalars().all()
    notes_index_list = [
        {
            "note_number": ni.note_number,
            "title": ni.title,
            "start_page": ni.start_page,
            "end_page": ni.end_page,
            "confidence": ni.confidence,
        }
        for ni in notes_index_rows
    ]
    note_extractions_list = [
        {
            "note_number": ne.note_number,
            "title": ne.title,
            "tables_json": ne.tables_json,
            "evidence_json": ne.evidence_json,
        }
        for ne in note_extraction_rows
    ]

    return DocumentVersionSummaryResponse(
        id=str(version.id),
        document_id=str(version.document_id),
        status=version.status,
        sha256=version.sha256,
        created_at=version.created_at.isoformat() if version.created_at else None,
        doc_type=doc.doc_type,
        original_filename=doc.original_filename,
        presentation_scale=pres_scale,
        canonical_mappings=mappings,
        note_classifications=notes,
        notes_index=notes_index_list if notes_index_list else None,
        note_extractions=note_extractions_list if note_extractions_list else None,
        reconciliation_checks=reconciliation_checks,
    )


@router.get("/versions/{version_id}/llm-input", response_model=LlmInputDebugResponse)
async def get_document_version_llm_input(
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Debug endpoint: return the raw page text that is sent to the LLM-based
    extraction pipeline, so users can download and inspect it.
    """
    result = await db.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == version_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    version, doc = row

    if not doc.storage_url:
        raise HTTPException(status_code=400, detail="Document has no storage_url")

    import fitz  # PyMuPDF

    pdf_bytes = download_file_from_url(doc.storage_url)
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    pages: list[dict] = []
    try:
        for i in range(len(pdf_doc)):
            page_no = i + 1
            text = pdf_doc[i].get_text() or ""
            pages.append(
                {
                    "region_id": f"page{page_no}",
                    "page": page_no,
                    "text": text[:2000],
                }
            )
    finally:
        pdf_doc.close()

    return LlmInputDebugResponse(
        id=str(version.id),
        document_id=str(version.document_id),
        pages=pages,
    )


@router.get("/versions/{version_id}/export")
async def export_statements(
    version_id: UUID,
    format: str = Query("xlsx", description="Export format: xlsx or csv"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Download extracted statements (and extraction summary) as CSV or Excel.
    Enables tracking of all extraction steps: Summary sheet + one sheet per statement (SFP, SCI, CF).
    """
    result = await db.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == version_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    version, doc = row

    stmt_result = await db.execute(
        select(Statement)
        .where(Statement.document_version_id == version.id)
        .options(selectinload(Statement.lines))
        .order_by(Statement.statement_type)
    )
    statements = list(stmt_result.scalars().unique().all())

    ni_result = await db.execute(
        select(NotesIndex).where(NotesIndex.document_version_id == version.id)
    )
    notes_index_rows = list(ni_result.scalars().all())
    ne_result = await db.execute(
        select(NoteExtraction).where(NoteExtraction.document_version_id == version.id)
    )
    note_extraction_rows = list(ne_result.scalars().all())

    ctx_result = await db.execute(
        select(PresentationContext).where(
            PresentationContext.document_version_id == version.id,
            PresentationContext.scope == "DOC",
            PresentationContext.scope_key == "presentation_scale",
        )
    )
    scale_ctx = ctx_result.scalars().first()
    presentation_scale = None
    if scale_ctx:
        presentation_scale = {
            "currency": getattr(scale_ctx, "currency", None),
            "scale": getattr(scale_ctx, "scale", None),
            "scale_factor": getattr(scale_ctx, "scale_factor", None),
        }

    canonical_ctx_result = await db.execute(
        select(PresentationContext).where(
            PresentationContext.document_version_id == version.id,
            PresentationContext.scope == "DOC",
            PresentationContext.scope_key == "canonical_mappings",
        )
    )
    canonical_ctx = canonical_ctx_result.scalars().first()
    canonical_mappings = canonical_ctx.evidence_json if canonical_ctx and canonical_ctx.evidence_json else None

    fmt = (format or "xlsx").lower().strip()
    if fmt not in ("xlsx", "csv"):
        fmt = "xlsx"

    safe_name = (doc.original_filename or "document").rsplit(".", 1)[0]
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in " ._-")[:50]
    filename = f"statements_{safe_name}_v{version_id.hex[:8]}.{fmt}"

    if not statements and canonical_mappings:
        if fmt == "csv":
            buf = build_mappings_csv(
                version_id=str(version.id),
                document_filename=doc.original_filename or "",
                status=version.status or "",
                canonical_mappings=canonical_mappings,
            )
            media_type = "text/csv"
        else:
            buf = build_mappings_xlsx(
                version_id=str(version.id),
                document_filename=doc.original_filename or "",
                status=version.status or "",
                canonical_mappings=canonical_mappings,
            )
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        buf = build_statements_csv(
            version_id=str(version.id),
            document_filename=doc.original_filename or "",
            status=version.status or "",
            statements=statements,
            presentation_scale=presentation_scale,
            notes_index=notes_index_rows if notes_index_rows else None,
            note_extractions=note_extraction_rows if note_extraction_rows else None,
        )
        media_type = "text/csv"
    else:
        buf = build_statements_xlsx(
            version_id=str(version.id),
            document_filename=doc.original_filename or "",
            status=version.status or "",
            statements=statements,
            presentation_scale=presentation_scale,
            notes_index=notes_index_rows if notes_index_rows else None,
            note_extractions=note_extraction_rows if note_extraction_rows else None,
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if not statements and not canonical_mappings:
        raise HTTPException(
            status_code=404,
            detail="No statement data or canonical mappings available yet. Ensure extraction has completed.",
        )

    return Response(
        content=buf.getvalue(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )

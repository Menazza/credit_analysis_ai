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
from app.models.extraction import PresentationContext, Statement, NotesIndex, NoteExtraction, NoteChunk
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
    engagement_id: str | None = None


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
    Simple summary for a document version - just the basics for download page.
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

    return DocumentVersionSummaryResponse(
        id=str(version.id),
        document_id=str(version.document_id),
        status=version.status,
        sha256=version.sha256,
        created_at=version.created_at.isoformat() if version.created_at else None,
        doc_type=doc.doc_type,
        original_filename=doc.original_filename,
        engagement_id=str(doc.engagement_id) if doc.engagement_id else None,
    )


@router.get("/versions/{version_id}/download-extracted")
async def download_extracted_files(
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Download the extracted files (Excel + JSON + notes summary) as a zip.
    Files are stored in S3 by the extraction pipeline.
    """
    import zipfile
    from app.services.storage import get_s3_client, get_settings
    
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
    
    if version.status != "MAPPED":
        raise HTTPException(status_code=400, detail="Extraction not complete yet")
    
    pdf_name = doc.original_filename or "document"
    if pdf_name.lower().endswith(".pdf"):
        pdf_name = pdf_name[:-4]
    
    # S3 keys for extracted files
    base_key = f"extracted/{doc.tenant_id}/{version.id}"
    files_to_download = [
        (f"{base_key}/statements_{pdf_name}.xlsx", f"statements_{pdf_name}.xlsx"),
        (f"{base_key}/notes_{pdf_name}.json", f"notes_{pdf_name}.json"),
        (f"{base_key}/notes_summary_{pdf_name}.txt", f"notes_summary_{pdf_name}.txt"),
    ]
    
    # Download files from S3 and create zip
    client = get_s3_client()
    bucket = get_settings().object_storage_bucket
    
    zip_buffer = io.BytesIO()
    files_found = 0
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for s3_key, filename in files_to_download:
            try:
                resp = client.get_object(Bucket=bucket, Key=s3_key)
                content = resp["Body"].read()
                zf.writestr(filename, content)
                files_found += 1
            except Exception as e:
                # File might not exist, skip it
                pass
    
    if files_found == 0:
        raise HTTPException(
            status_code=404, 
            detail=f"No extracted files found for {pdf_name}. Extraction may have failed."
        )
    
    zip_buffer.seek(0)
    
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="extracted_{pdf_name}.zip"',
        },
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


class NoteChunksRequest(BaseModel):
    note_ids: list[str]
    max_tokens: int | None = 15000
    scope: str = "GROUP"


class NoteChunkResponse(BaseModel):
    chunk_id: str
    note_id: str
    title: str
    text: str
    page_start: int | None
    page_end: int | None
    tables_json: list
    keywords: list


@router.post("/versions/{version_id}/notes/chunks", response_model=list[NoteChunkResponse])
async def fetch_note_chunks_endpoint(
    version_id: UUID,
    body: NoteChunksRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Fetch note chunks by note_ids. Caps total tokens if max_tokens set.
    Used by the "ask for section when needed" flow.
    """
    result = await db.execute(
        select(DocumentVersion, Document).join(Document, Document.id == DocumentVersion.document_id).where(
            DocumentVersion.id == version_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    version, _doc = row

    if not body.note_ids:
        return []

    q = (
        select(NoteChunk)
        .where(
            NoteChunk.document_version_id == version.id,
            NoteChunk.scope == body.scope,
            NoteChunk.note_id.in_(body.note_ids),
        )
        .order_by(NoteChunk.note_id, NoteChunk.chunk_id)
    )
    r = await db.execute(q)
    chunks = list(r.scalars().unique().all())

    out: list[NoteChunkResponse] = []
    total_tokens = 0
    for nc in chunks:
        tok = nc.tokens_approx or (len((nc.text or "")) // 4)
        if body.max_tokens and total_tokens + tok > body.max_tokens:
            break
        out.append(NoteChunkResponse(
            chunk_id=nc.chunk_id,
            note_id=nc.note_id,
            title=nc.title or "",
            text=nc.text or "",
            page_start=nc.page_start,
            page_end=nc.page_end,
            tables_json=nc.tables_json or [],
            keywords=nc.keywords_json or [],
        ))
        total_tokens += tok
    return out


@router.get("/versions/{version_id}/notes/search", response_model=list[str])
async def search_notes_endpoint(
    version_id: UUID,
    q: str = Query(..., min_length=2),
    top_k: int = Query(5, ge=1, le=20),
    scope: str = Query("GROUP"),
    hybrid: bool = Query(True, description="Use hybrid (tsvector + semantic) search"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Search notes. Returns chunk_ids. Use hybrid=true for tsvector + semantic; false for keyword only.
    """
    result = await db.execute(
        select(DocumentVersion).join(Document, Document.id == DocumentVersion.document_id).where(
            DocumentVersion.id == version_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    import asyncio
    from app.worker.tasks import get_sync_session
    from app.services.notes_retrieval import search_notes_hybrid, search_notes_keyword

    def _search():
        sess = get_sync_session()
        try:
            if hybrid:
                return search_notes_hybrid(sess, str(version.id), q, scope, top_k)
            return search_notes_keyword(sess, str(version.id), q, scope, top_k)
        finally:
            sess.close()

    return await asyncio.to_thread(_search)

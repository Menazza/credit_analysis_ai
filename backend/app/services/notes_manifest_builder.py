"""
Build Notes Manifest from index + chunks. Store in PresentationContext.

Manifest structure (tiny, safe to include in prompts):
- notes: [{note_id, title, subsections, page_range, period_end?, scope, contains_tables, keywords}]
"""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.models.extraction import NoteChunk, NotesIndex, PresentationContext


def build_notes_manifest(
    db: Session,
    document_version_id: str,
    scope: str = "GROUP",
    period_end: str | None = None,
) -> dict[str, Any]:
    """
    Build manifest from note_chunks (and optionally NotesIndex for page_range).
    Returns manifest dict; also persists to PresentationContext.
    """
    chunks = db.query(NoteChunk).filter(
        NoteChunk.document_version_id == document_version_id,
        NoteChunk.scope == scope,
    ).order_by(NoteChunk.note_id, NoteChunk.chunk_id).all()

    # Group by note_id
    by_note: dict[str, list[NoteChunk]] = {}
    for c in chunks:
        by_note.setdefault(c.note_id, []).append(c)

    notes_list: list[dict[str, Any]] = []
    index_entries = {
        str(ni.note_number): ni
        for ni in db.query(NotesIndex).filter(
            NotesIndex.document_version_id == document_version_id,
        ).all()
    }

    for note_id, chunk_list in sorted(by_note.items()):
        note_num = note_id.split(":")[-1].split(".")[0] if ":" in note_id else note_id
        first = chunk_list[0]
        subsections = [c.title or c.chunk_id for c in chunk_list if c.title]
        page_start = first.page_start
        page_end = max((c.page_end or c.page_start or 0) for c in chunk_list)
        ni = index_entries.get(note_num)
        if ni:
            page_start = page_start or ni.start_page
            page_end = page_end or ni.end_page or ni.start_page

        all_keywords: set[str] = set()
        has_tables = False
        for c in chunk_list:
            all_keywords.update(c.keywords_json or [])
            if c.tables_json and len(c.tables_json) > 0:
                has_tables = True

        notes_list.append({
            "note_id": note_id,
            "title": first.title or (ni.title if ni else note_id),
            "subsections": subsections[:20],
            "page_range": f"p{page_start}" if page_start else None,
            "period_end": period_end,
            "scope": scope,
            "contains_tables": has_tables,
            "keywords": list(all_keywords)[:15],
        })

    manifest = {"notes": notes_list, "scope": scope}
    scope_key = f"notes_manifest_{scope}"

    # Upsert PresentationContext
    ctx = db.query(PresentationContext).filter(
        PresentationContext.document_version_id == document_version_id,
        PresentationContext.scope == "DOC",
        PresentationContext.scope_key == scope_key,
    ).first()

    if ctx:
        ctx.evidence_json = manifest
    else:
        ctx = PresentationContext(
            document_version_id=document_version_id,
            scope="DOC",
            scope_key=scope_key,
            evidence_json=manifest,
        )
        db.add(ctx)

    return manifest

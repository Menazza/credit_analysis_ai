"""
Notes retrieval: manifest, fetch chunks, search. On-demand only – never dump raw notes.
Hybrid search: tsvector (BM25-style) + vector (semantic).
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.extraction import NoteChunk, NotesIndex, PresentationContext
from app.services.note_router import route_to_notes
from app.services.notes_embedding import get_embedding


def get_notes_manifest(
    db: Session,
    document_version_id: str,
    scope: str = "GROUP",
) -> dict[str, Any] | None:
    """
    Return compact manifest for LLM: note_id, title, subsections, page_range, keywords.
    Stored in PresentationContext scope_key=notes_manifest_{scope}.
    """
    ctx = db.query(PresentationContext).filter(
        PresentationContext.document_version_id == document_version_id,
        PresentationContext.scope == "DOC",
        PresentationContext.scope_key == f"notes_manifest_{scope}",
    ).first()
    if ctx and ctx.evidence_json:
        return ctx.evidence_json
    return None


def fetch_note_chunks(
    db: Session,
    document_version_id: str,
    note_ids: list[str],
    scope: str = "GROUP",
    max_tokens: int | None = 15000,
) -> list[dict[str, Any]]:
    """
    Fetch chunks for given note_ids. Caps total tokens if max_tokens set.
    Returns list of {chunk_id, note_id, title, text, page_start, page_end, tables_json, keywords}.
    """
    if not note_ids:
        return []

    query = db.query(NoteChunk).filter(
        NoteChunk.document_version_id == document_version_id,
        NoteChunk.scope == scope,
        NoteChunk.note_id.in_(note_ids),
    ).order_by(NoteChunk.note_id, NoteChunk.chunk_id)

    chunks: list[dict[str, Any]] = []
    total_tokens = 0
    for nc in query.all():
        tok = nc.tokens_approx or (len((nc.text or "")) // 4)
        if max_tokens and total_tokens + tok > max_tokens:
            break
        chunks.append({
            "chunk_id": nc.chunk_id,
            "note_id": nc.note_id,
            "title": nc.title or "",
            "text": nc.text or "",
            "page_start": nc.page_start,
            "page_end": nc.page_end,
            "tables_json": nc.tables_json or [],
            "keywords": nc.keywords_json or [],
        })
        total_tokens += tok

    return chunks


def search_notes_tsvector(
    db: Session,
    document_version_id: str,
    query: str,
    scope: str = "GROUP",
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Full-text search using Postgres tsvector. Returns [(chunk_id, rank_score), ...].
    """
    if not query or len(query.strip()) < 2:
        return []
    q = query.strip().replace("'", "''")
    stmt = text("""
        SELECT nc.id, nc.chunk_id,
               ts_rank(to_tsvector('english', COALESCE(nc.title, '') || ' ' || COALESCE(nc.text, '')),
                       plainto_tsquery('english', :q)) AS rank
        FROM note_chunks nc
        WHERE nc.document_version_id = :dv_id AND nc.scope = :scope
          AND to_tsvector('english', COALESCE(nc.title, '') || ' ' || COALESCE(nc.text, ''))
              @@ plainto_tsquery('english', :q)
        ORDER BY rank DESC
        LIMIT :top_k
    """)
    rows = db.execute(stmt, {"q": q, "dv_id": str(document_version_id), "scope": scope, "top_k": top_k}).fetchall()
    return [(r[1], float(r[2] or 0)) for r in rows]


def search_notes_semantic(
    db: Session,
    document_version_id: str,
    query: str,
    scope: str = "GROUP",
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Vector similarity search (cosine). Returns [(chunk_id, distance), ...].
    Requires pgvector and pre-computed embeddings.
    """
    try:
        emb = get_embedding(query)
    except Exception:
        return []
    if not emb or len(emb) != 1536:
        return []

    stmt = text("""
        SELECT chunk_id, 1 - (embedding <=> :emb::vector) AS similarity
        FROM note_chunks
        WHERE document_version_id = :dv_id AND scope = :scope AND embedding IS NOT NULL
        ORDER BY embedding <=> :emb2::vector
        LIMIT :top_k
    """)
    emb_str = "[" + ",".join(str(x) for x in emb) + "]"
    rows = db.execute(stmt, {
        "emb": emb_str, "emb2": emb_str,
        "dv_id": str(document_version_id), "scope": scope, "top_k": top_k
    }).fetchall()
    return [(r[0], float(r[1] or 0)) for r in rows]


def search_notes_hybrid(
    db: Session,
    document_version_id: str,
    query: str,
    scope: str = "GROUP",
    top_k: int = 5,
    keyword_weight: float = 0.5,
) -> list[str]:
    """
    Hybrid search: combine tsvector and semantic. Returns chunk_ids.
    """
    results: dict[str, float] = {}
    ts = search_notes_tsvector(db, document_version_id, query, scope, top_k * 2)
    sem = search_notes_semantic(db, document_version_id, query, scope, top_k * 2)

    # Normalize and combine (ts_rank and similarity have different scales)
    def _norm(rows: list[tuple[str, float]]) -> dict[str, float]:
        if not rows:
            return {}
        max_v = max(r[1] for r in rows)
        return {r[0]: (r[1] / max_v if max_v else 0) for r in rows}

    ts_scores = _norm(ts)
    sem_scores = _norm(sem)
    for cid, s in ts_scores.items():
        results[cid] = results.get(cid, 0) + keyword_weight * s
    for cid, s in sem_scores.items():
        results[cid] = results.get(cid, 0) + (1 - keyword_weight) * s

    sorted_ids = sorted(results.keys(), key=lambda x: -results[x])
    return sorted_ids[:top_k]


def search_notes_keyword(
    db: Session,
    document_version_id: str,
    query: str,
    scope: str = "GROUP",
    top_k: int = 5,
) -> list[str]:
    """
    Keyword search. Prefer search_notes_tsvector when available; this is fallback.
    """
    ts = search_notes_tsvector(db, document_version_id, query, scope, top_k)
    if ts:
        return [r[0] for r in ts]
    words = [w.lower() for w in query.split() if len(w) > 2]
    if not words:
        return []

    all_chunks = db.query(NoteChunk).filter(
        NoteChunk.document_version_id == document_version_id,
        NoteChunk.scope == scope,
    ).all()

    scored: list[tuple[int, str]] = []
    for nc in all_chunks:
        txt = (nc.text or "").lower()
        keywords = [str(k).lower() for k in (nc.keywords_json or [])]
        score = sum(1 for w in words if w in txt or w in " ".join(keywords))
        if score > 0:
            scored.append((score, nc.chunk_id))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]

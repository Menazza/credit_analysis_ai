"""
Split note text into retrieval chunks at semantic boundaries.

Chunk at subsection level (21.1, 21.2, etc.) to keep payloads small and targeted.
Target ~500-1,500 tokens per chunk. Store with note_id (GROUP:21), chunk_id (GROUP:21.1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NoteChunkData:
    note_id: str
    chunk_id: str
    title: str
    page_start: int | None
    page_end: int | None
    text: str
    tables_json: list = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


# Match "21.1 Reconciliation...", "21.2 ABSA Bank", "Note 21.3" etc.
SUBSECTION_PATTERN = re.compile(
    r"(?i)(?:Note\s+)?(\d+)[\.\s\-–—]+(\d+)[\.\s\-–—]*\s*([^\n]+)"
)
# Match "21. Reconciliation" (note + first subsection without sub-num)
NOTE_HEADER_PATTERN = re.compile(
    r"(?i)(?:Note\s+)?(\d+)[\.\s\-–—]+\s*([^\n]+)"
)
# Approximate tokens: ~4 chars per token
CHARS_PER_TOKEN = 4
TARGET_CHUNK_TOKENS = 800
MAX_CHUNK_CHARS = 2500


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _extract_keywords(text: str, max_keywords: int = 15) -> list[str]:
    """Simple keyword extraction: uppercase/Title terms, known financial terms."""
    known = {
        "JIBAR", "ECL", "ROU", "IFRS", "sale and leaseback", "gearing",
        "borrowings", "lease", "maturity", "covenant", "interest", "facility",
        "unsecured", "revolving", "credit risk", "impairment",
    }
    found: set[str] = set()
    lower = text.lower()
    for k in known:
        if k.lower() in lower:
            found.add(k)
    # Add any ALL CAPS words 4+ chars
    for m in re.finditer(r"\b([A-Z]{4,})\b", text):
        found.add(m.group(1))
    return list(found)[:max_keywords]


def chunk_note_text(
    full_text: str,
    scope: str,
    note_number: str,
    title: str,
    page_start: int | None = None,
    page_end: int | None = None,
) -> list[NoteChunkData]:
    """
    Split note text at subsection boundaries. Returns list of chunks.

    note_number: e.g. "21"
    scope: GROUP or COMPANY
    """
    note_id = f"{scope}:{note_number}"
    chunks: list[NoteChunkData] = []

    # Find subsection starts: (start_pos, sub_num, sub_title)
    sub_matches: list[tuple[int, str, str]] = []
    for m in SUBSECTION_PATTERN.finditer(full_text):
        num, sub, sub_title = m.group(1), m.group(2), m.group(3).strip()
        if num == note_number:
            sub_matches.append((m.start(), sub, sub_title[:200]))

    if not sub_matches:
        # No subsections: single chunk for whole note
        text = full_text.strip()[:12000]
        if text:
            chunks.append(NoteChunkData(
                note_id=note_id,
                chunk_id=note_id,
                title=title[:500],
                page_start=page_start,
                page_end=page_end,
                text=text,
                keywords=_extract_keywords(text),
            ))
        return chunks

    # Chunk by subsection
    for i, (start, sub, sub_title) in enumerate(sub_matches):
        end = sub_matches[i + 1][0] if i + 1 < len(sub_matches) else len(full_text)
        body = full_text[start:end].strip()
        if not body or len(body) < 50:
            continue
        chunk_id = f"{note_id}.{sub}"
        # Truncate if very long
        if len(body) > MAX_CHUNK_CHARS:
            body = body[:MAX_CHUNK_CHARS] + "\n[...truncated]"
        chunks.append(NoteChunkData(
            note_id=note_id,
            chunk_id=chunk_id,
            title=sub_title[:200] or title,
            page_start=page_start,
            page_end=page_end,
            text=body,
            keywords=_extract_keywords(body),
        ))

    # If we have subsections but the intro (before first subsection) is substantial, add it
    first_start = sub_matches[0][0]
    intro = full_text[:first_start].strip()
    if len(intro) > 200:
        chunks.insert(0, NoteChunkData(
            note_id=note_id,
            chunk_id=f"{note_id}.0",
            title=f"{title} (intro)",
            page_start=page_start,
            page_end=page_end,
            text=intro[:MAX_CHUNK_CHARS],
            keywords=_extract_keywords(intro),
        ))

    return chunks

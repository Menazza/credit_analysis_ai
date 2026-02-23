"""
Notes indexing for risks and debt structure.
Keyword-based extraction with citations (note id, pages).
"""
from __future__ import annotations

import re
from typing import Any

_RISK_KEYWORDS = [
    "risk", "uncertainty", "contingent", "litigation", "guarantee",
    "covenant", "default", "breach", "material adverse",
]
_DEBT_KEYWORDS = [
    "borrowing", "debt", "loan", "facility", "security", "pledge",
    "mortgage", "debenture", "interest rate", "maturity",
]


def _excerpt(text: str, keyword: str, context_chars: int = 150) -> str:
    """Extract an excerpt around the first occurrence of keyword."""
    if not text or not keyword:
        return ""
    t = text.lower()
    k = keyword.lower()
    pos = t.find(k)
    if pos < 0:
        return ""
    start = max(0, pos - context_chars)
    end = min(len(text), pos + len(keyword) + context_chars)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt = excerpt + "..."
    return excerpt.strip()


def index_notes_for_risks(notes: dict[str, Any]) -> list[dict[str, str]]:
    """
    Extract risk-related excerpts from notes with citations.
    Returns list of {note_id, title, pages, excerpt, keyword}.
    """
    results = []
    for note_id, note in (notes.get("notes") or notes).items():
        if not isinstance(note, dict):
            continue
        title = note.get("title") or ""
        pages = note.get("pages") or ""
        text = (note.get("text") or "")[:5000]
        for kw in _RISK_KEYWORDS:
            if kw.lower() in text.lower():
                excerpt = _excerpt(text, kw)
                if excerpt:
                    results.append({
                        "note_id": str(note_id),
                        "title": title,
                        "pages": pages,
                        "excerpt": excerpt[:300],
                        "keyword": kw,
                    })
    return results[:15]


def index_notes_for_debt(notes: dict[str, Any]) -> list[dict[str, str]]:
    """
    Extract debt-structure excerpts from notes with citations.
    """
    results = []
    for note_id, note in (notes.get("notes") or notes).items():
        if not isinstance(note, dict):
            continue
        title = note.get("title") or ""
        pages = note.get("pages") or ""
        text = (note.get("text") or "")[:5000]
        for kw in _DEBT_KEYWORDS:
            if kw.lower() in text.lower():
                excerpt = _excerpt(text, kw)
                if excerpt:
                    results.append({
                        "note_id": str(note_id),
                        "title": title,
                        "pages": pages,
                        "excerpt": excerpt[:300],
                        "keyword": kw,
                    })
    return results[:15]


def format_risks_for_memo(notes_json: dict[str, Any] | None) -> str:
    """Format risk excerpts as memo section text."""
    if not notes_json:
        return "Key risks: content to be populated from notes."
    items = index_notes_for_risks(notes_json)
    if not items:
        return "No risk-related disclosures identified in notes."
    lines = []
    for r in items:
        lines.append(f"Note {r['note_id']} ({r['title']}), p.{r['pages']}: {r['excerpt']}")
    return "\n\n".join(lines)

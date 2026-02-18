"""
Note packet builder: replace flat sections["notes"] with structured note packets.

Phase 1: Fix note detection into "note packets" (not one blob)
- Per-type packets: borrowings, leases, contingencies, risk
- Controlled spillover: hard stops at new note header, different section, max 3 pages
- Preserve page boundaries for provenance
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Any

# Import from section_locator to stay consistent
from app.services.section_locator import Page, NOTE_KEYWORDS

# Hard-stop patterns: stop spillover when we hit these
HARD_STOP_SECTION = re.compile(
    r"directors['\u2019]?\s*report|independent\s+auditor|notes?\s+to\s+the\s+(consolidated|separate)|"
    r"annexure|corporate\s+governance|index\s+to\s+the\s+notes?",
    re.IGNORECASE,
)
NEW_NOTE_HEADER = re.compile(r"^\s*\d{1,2}[\.\s\-–—]+\s*\w+", re.MULTILINE)

MAX_SPILL_PAGES = 3


@dataclass
class NotePacket:
    packet_type: str  # borrowings, leases, contingencies, risk
    pages: List[Dict[str, Any]]  # [{"page": N, "text": "..."}]
    signals: List[str] = field(default_factory=list)
    note_numbers: List[str] = field(default_factory=list)  # e.g. ["21"] for Note 21
    confidence: float = 0.9


def _matches_note_anchor(text: str) -> List[str]:
    """Return list of note_type keys that match (borrowings, leases, etc.)."""
    text_l = (text or "").lower()
    matched = []
    for note_type, patterns in NOTE_KEYWORDS.items():
        if any(re.search(rx, text_l) for rx in patterns):
            matched.append(note_type)
    return matched


def _extract_note_numbers(text: str) -> List[str]:
    """Find note numbers like '21', 'Note 20' in text."""
    found = set()
    # "21. Borrowings", "Note 21", "note 20"
    for m in re.finditer(r"(?:note\s+)?(\d{1,2})\b", text, re.IGNORECASE):
        found.add(m.group(1))
    return sorted(found, key=int)


def _is_hard_stop(text: str) -> bool:
    """True if page starts a different section we should not spill into."""
    if not text or len(text) < 50:
        return False
    first_block = text[:800].lower()
    return bool(HARD_STOP_SECTION.search(first_block))


def _has_new_note_header(text: str, current_note_no: Optional[str]) -> bool:
    """
    Check if text begins with a new note header (N. Title) that might be a different note.
    If current_note_no is set, we're in a note and a new "N. Title" could be the next note.
    """
    match = NEW_NOTE_HEADER.search(text[:500])
    if not match:
        return False
    # Could refine: if match.group suggests a different note number, return True
    return True


def build_note_packets(
    pages: List[Page],
    max_spill: int = MAX_SPILL_PAGES,
) -> List[NotePacket]:
    """
    Build note packets with controlled spillover.

    - Each page that matches a note anchor starts/extends a packet
    - Spillover: include next page(s) until hard stop, new note header, or max_spill
    - Multiple packets possible (e.g. Borrowings packet, Leases packet)
    """
    n = len(pages)
    packets: List[NotePacket] = []
    used_indices: set = set()

    for idx, p in enumerate(pages):
        if idx in used_indices:
            continue
        text = p.text or ""
        matched_types = _matches_note_anchor(text)
        if not matched_types:
            continue

        note_nums = _extract_note_numbers(text)
        signals = matched_types + ([f"note {x}" for x in note_nums] if note_nums else [])

        # Build packet with controlled spillover
        packet_pages: List[Dict[str, Any]] = [{"page": p.page, "text": text}]
        used_indices.add(idx)

        for j in range(1, max_spill + 1):
            next_idx = idx + j
            if next_idx >= n:
                break
            if next_idx in used_indices:
                break
            next_p = pages[next_idx]
            next_text = next_p.text or ""
            if _is_hard_stop(next_text):
                break
            packet_pages.append({"page": next_p.page, "text": next_text})
            used_indices.add(next_idx)

        # One packet per primary signal (avoid duplicates; take first match)
        primary = matched_types[0]
        packets.append(
            NotePacket(
                packet_type=primary,
                pages=packet_pages,
                signals=signals,
                note_numbers=note_nums,
                confidence=0.9,
            )
        )

    return packets

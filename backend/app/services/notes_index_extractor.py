"""
Notes index extractor: find Notes index/contents and populate NotesIndex.

Phase 2: Build a NotesIndex (even if imperfect)
- Find "Notes to the annual financial statements", "Index to the notes"
- Parse list like "21 Borrowings … page 138"
- Populate NotesIndex with (note_no, title, start_page, end_page)
- Fallback: header-based discovery from note packets
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.services.section_locator import Page


@dataclass
class NotesIndexEntry:
    note_number: str
    title: str
    start_page: int
    end_page: int
    confidence: float
    source: str  # "index" | "packet_header"


INDEX_ANCHORS = [
    r"notes?\s+to\s+(the\s+)?(consolidated|annual)\s+financial\s+statements",
    r"index\s+to\s+the\s+notes?",
    r"notes?\s+page\s*\d+",
]

# "21 Borrowings … 138" or "Note 21 Borrowings 138" or "21 Borrowings 138"
NOTE_INDEX_LINE = re.compile(
    r"(?:note\s+)?(\d{1,2})[\.\s\-–—]*\s*([^\d\n]{3,60}?)\s*(?:\s+\.{2,}\s*)?\s*(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Simpler: "21 Borrowings 138" (note, title, page)
NOTE_INDEX_LINE_SIMPLE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z][A-Za-z\s\-–—]{2,50}?)\s+(\d{2,3})\b",
)


def _find_index_region(pages: List[Page]) -> Optional[Tuple[int, int]]:
    """
    Find the page range that contains the notes index/contents.
    Returns (start_idx, end_idx) in pages list, or None.
    """
    for idx, p in enumerate(pages):
        text = (p.text or "").lower()
        for anchor in INDEX_ANCHORS:
            if re.search(anchor, text):
                # Include this page and maybe next (index often spans 1-2 pages)
                return (idx, min(idx + 2, len(pages) - 1))
    return None


def extract_notes_index_from_pages(pages: List[Page]) -> List[NotesIndexEntry]:
    """
    Try to extract note number, title, page from an index/contents region.
    Fallback: return empty list (caller will use packet-based discovery).
    """
    region = _find_index_region(pages)
    if not region:
        return []

    entries: List[NotesIndexEntry] = []
    start_idx, end_idx = region

    for idx in range(start_idx, end_idx + 1):
        if idx >= len(pages):
            break
        text = pages[idx].text or ""
        page_no = pages[idx].page

        for m in NOTE_INDEX_LINE.finditer(text):
            note_num, title, pg = m.group(1), m.group(2).strip(), m.group(3)
            try:
                start_pg = int(pg)
            except ValueError:
                continue
            entries.append(
                NotesIndexEntry(
                    note_number=note_num,
                    title=title[:200],
                    start_page=start_pg,
                    end_page=start_pg,  # will infer from next entry
                    confidence=0.85,
                    source="index",
                )
            )

        if not entries:
            for m in NOTE_INDEX_LINE_SIMPLE.finditer(text):
                note_num, title, pg = m.group(1), m.group(2).strip(), m.group(3)
                try:
                    start_pg = int(pg)
                except ValueError:
                    continue
                entries.append(
                    NotesIndexEntry(
                        note_number=note_num,
                        title=title[:200],
                        start_page=start_pg,
                        end_page=start_pg,
                        confidence=0.75,
                        source="index",
                    )
                )

    # Infer end_page from next entry's start_page
    for i in range(len(entries) - 1):
        entries[i].end_page = entries[i + 1].start_page - 1
        if entries[i].end_page < entries[i].start_page:
            entries[i].end_page = entries[i].start_page

    return entries


def infer_index_from_packets(packets: List[dict]) -> List[NotesIndexEntry]:
    """
    Fallback: build NotesIndex entries from note packets when no index found.
    packets: list of {"packet_type", "pages", "signals", "note_numbers"}
    """
    entries: List[NotesIndexEntry] = []
    for pkt in packets:
        pages_list = pkt.get("pages", [])
        if not pages_list:
            continue
        note_nums = pkt.get("note_numbers", [])
        note_type = pkt.get("packet_type", "OTHER")
        page_nums = [pg["page"] for pg in pages_list]
        start_pg = min(page_nums)
        end_pg = max(page_nums)
        note_no = str(note_nums[0]) if note_nums else "?"
        entries.append(
            NotesIndexEntry(
                note_number=note_no,
                title=note_type.replace("_", " ").title(),
                start_page=start_pg,
                end_page=end_pg,
                confidence=0.7 if note_nums else 0.6,
                source="packet_header",
            )
        )
    return entries

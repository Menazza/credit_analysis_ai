"""
Section locator and page packet builder for AFS PDFs / OCR JSON.

Purpose:
- Given page-level text, deterministically detect which pages contain
  key statements (SOFP, SOCI, cash flow) and important notes.
- Detect presentation currency/scale.
- Build LLM snippet packets that include only those pages (with
  page boundaries preserved) plus meta and scale hints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import re


@dataclass
class Page:
    page: int
    text: str


# --- Anchors for statements and notes ---

STATEMENT_ANCHORS: Dict[str, List[str]] = {
    "sofp": [
        r"consolidated statement of financial position",
        r"\bstatement of financial position\b",
        r"\bbalance sheet\b",
    ],
    "soci": [
        r"consolidated statement of (comprehensive income|profit and loss|profit or loss)",
        r"\bstatement of comprehensive income\b",
        r"\bincome statement\b",
    ],
    "cashflow": [
        r"consolidated statement of cash flows?",
        r"\bcash flow statement\b",
    ],
}

NOTE_KEYWORDS: Dict[str, List[str]] = {
    "borrowings": [
        r"\bborrowings\b",
        r"interest[- ]bearing borrowings",
        r"note\s*21\b.*borrowings",
        r"\b21\.\s*borrowings\b",
    ],
    "leases": [
        r"\blease liabilities\b",
        r"\bleases?\b",
        r"note\s*20\b.*leases?",
    ],
    "contingencies": [
        r"\bcontingent liabilities\b",
        r"\bcontingencies\b",
    ],
    "risk": [
        r"risk management and financial instrument disclosure",
        r"\bfinancial risk management\b",
    ],
}


def detect_scale_and_currency(pages: List[Page]) -> Dict[str, Optional[str]]:
    """
    Heuristic presentation currency and scale detection from the first few pages.

    Returns: {"currency": "ZAR"/"USD"/..., "scale": "units"/"thousand"/"million"/"billion", "scale_factor": float}
    """
    head_text = "\n".join((p.text or "") for p in pages[:3]).lower()

    currency: Optional[str] = None
    if "south africa rand" in head_text or "south african rand" in head_text:
        currency = "ZAR"
    elif "us dollar" in head_text or "u.s. dollar" in head_text or "usd" in head_text:
        currency = "USD"
    elif "euro" in head_text:
        currency = "EUR"

    scale = "units"
    factor = 1.0
    if re.search(r"\br\s*m\b|\br million\b|\bamounts? in (r|zar) million", head_text):
        scale, factor = "million", 1e6
    elif re.search(r"r'?000\b|\bamounts? in thousands", head_text):
        scale, factor = "thousand", 1e3
    elif re.search(r"\bamounts? in (r|zar) billions?", head_text):
        scale, factor = "billion", 1e9

    return {"currency": currency, "scale": scale, "scale_factor": factor}


def _score_page_for_section(text: str, patterns: List[str]) -> float:
    text_l = (text or "").lower()
    score = 0.0
    for rx in patterns:
        if re.search(rx, text_l):
            score += 1.0
    if "continued" in text_l:
        score += 0.2
    return score


def detect_sections_with_spillover(pages: List[Page]) -> Dict[str, List[Page]]:
    """
    Returns pages per section, with spillover (prev/next pages) included.

    Keys:
      "sofp", "soci", "cashflow", "notes"
    """
    n = len(pages)
    by_section_indices: Dict[str, List[int]] = {k: [] for k in STATEMENT_ANCHORS.keys()}
    notes_pages: Dict[str, List[int]] = {k: [] for k in NOTE_KEYWORDS.keys()}

    # 1) Score pages
    for idx, p in enumerate(pages):
        text = p.text or ""
        for sec, patterns in STATEMENT_ANCHORS.items():
            s = _score_page_for_section(text, patterns)
            if s >= 0.9:
                by_section_indices[sec].append(idx)
        for note_type, patterns in NOTE_KEYWORDS.items():
            if any(re.search(rx, text, re.IGNORECASE) for rx in patterns):
                notes_pages[note_type].append(idx)

    # 2) Spillover helper
    def add_spill(indices: List[int]) -> List[int]:
        expanded = set()
        for i in indices:
            for j in (i - 1, i, i + 1):
                if 0 <= j < n:
                    expanded.add(j)
        return sorted(expanded)

    for sec in by_section_indices:
        by_section_indices[sec] = add_spill(by_section_indices[sec])
    for note_type in notes_pages:
        notes_pages[note_type] = add_spill(notes_pages[note_type])

    # 3) Build output
    out: Dict[str, List[Page]] = {}
    for sec, idxs in by_section_indices.items():
        out[sec] = [pages[i] for i in idxs]

    notes_all_idx = sorted({i for idxs in notes_pages.values() for i in idxs})
    out["notes"] = [pages[i] for i in notes_all_idx]  # legacy flat list; prefer note_packets

    return out


def detect_sections_and_note_packets(pages: List[Page]) -> tuple[Dict[str, List[Page]], List[Dict]]:
    """
    Returns (sections, note_packets).
    sections: {sofp, soci, cashflow, notes} - statements + legacy flat notes
    note_packets: list of {packet_type, pages, signals, note_numbers, confidence}
    """
    from app.services.note_packets import build_note_packets

    sections = detect_sections_with_spillover(pages)
    packets = build_note_packets(pages)
    packet_dicts = [
        {
            "packet_type": p.packet_type,
            "pages": p.pages,
            "signals": p.signals,
            "note_numbers": p.note_numbers,
            "confidence": p.confidence,
        }
        for p in packets
    ]
    return sections, packet_dicts


def build_llm_packets(
    pages_by_section: Dict[str, List[Page]],
    doc_meta: Dict,
    scale_info: Dict[str, Optional[str]],
) -> List[Dict]:
    """
    Build per-section LLM packets, keeping page boundaries.
    """
    packets: List[Dict] = []

    for section_name, pages in pages_by_section.items():
        if not pages:
            continue
        pkt = {
            "section_name": section_name,
            "doc_meta": {
                "doc_id": doc_meta.get("doc_id"),
                "company_name": doc_meta.get("company_name"),
                "year_end": doc_meta.get("year_end"),
            },
            "scale_hint": {
                "currency": scale_info.get("currency"),
                "scale": scale_info.get("scale"),
                "scale_factor": scale_info.get("scale_factor"),
            },
            "pages": [
                {"page": p.page, "text": p.text or ""}
                for p in sorted(pages, key=lambda x: x.page)
            ],
        }
        packets.append(pkt)

    return packets


"""Covenant Engine - extract covenants from Note 43/48, compute headroom."""
from __future__ import annotations
import re
from typing import Any
from app.core.section_schema import score_to_rating

def _parse_covenants(notes: dict) -> dict:
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    out = {"leverage_max": 2.75, "interest_cover_min": 3.5, "undrawn_bn": None}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:12000]
        if "covenant" not in text.lower() and "going concern" not in text.lower():
            continue
        m = re.search(r"exceed\s+(\d+\.?\d*)\s*times", text, re.I)
        if m:
            out["leverage_max"] = float(m.group(1))
        m = re.search(r"minimum\s+of\s+(\d+\.?\d*)\s*times", text, re.I)
        if m:
            out["interest_cover_min"] = float(m.group(1))
        m = re.search(r"([\d,\.]+)\s*(?:bn|billion)", text, re.I)
        if m:
            try:
                out["undrawn_bn"] = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return out

def run_covenant_engine(notes_json: dict | None, nd_ebitda: float | None, interest_cover: float | None, undrawn_facilities: float | None) -> dict[str, Any]:
    block: dict[str, Any] = {"section_name": "Covenants & Headroom", "key_metrics": {}, "score": 70.0, "section_rating": "Adequate", "risk_flags": [], "evidence_notes": ["Note 48: Going concern", "Note 43.4.3: Covenant terms"], "llm_commentary": ""}
    parsed = _parse_covenants(notes_json or {})
    lev_max = parsed["leverage_max"]
    ic_min = parsed["interest_cover_min"]
    block["key_metrics"]["covenant_leverage_max"] = lev_max
    block["key_metrics"]["covenant_interest_cover_min"] = ic_min
    block["key_metrics"]["current_nd_ebitda"] = nd_ebitda
    block["key_metrics"]["current_interest_cover"] = interest_cover
    block["key_metrics"]["undrawn_facilities"] = undrawn_facilities or parsed["undrawn_bn"]
    headroom_score = 70.0
    if nd_ebitda is not None and nd_ebitda < lev_max:
        pct = 100 * (lev_max - nd_ebitda) / lev_max
        block["key_metrics"]["leverage_headroom_pct"] = round(pct, 1)
        block["key_metrics"]["leverage_breach"] = False
        headroom_score = 95 if nd_ebitda < 0 else (85 if pct >= 30 else 75)
    elif nd_ebitda is not None and nd_ebitda >= lev_max:
        block["risk_flags"].append("Covenant breach: ND/EBITDA at or above limit")
        block["key_metrics"]["leverage_breach"] = True
        block["key_metrics"]["leverage_breach_distance"] = round(nd_ebitda - lev_max, 2)
        headroom_score = 15
    if interest_cover is not None and interest_cover < ic_min:
        block["risk_flags"].append("Covenant breach: Interest cover below minimum")
        block["key_metrics"]["interest_cover_breach"] = True
        block["key_metrics"]["interest_cover_breach_distance"] = round(ic_min - interest_cover, 2)
        headroom_score = min(headroom_score, 15)
    else:
        block["key_metrics"]["interest_cover_breach"] = False
    section_score = max(0, min(100, headroom_score))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    return block

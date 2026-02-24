"""Covenant Headroom Engine - extract covenants from Note 43/48, compute headroom, stress headroom, covenant risk score."""
from __future__ import annotations
import re
from typing import Any
from app.core.section_schema import score_to_rating


def _parse_covenants(notes: dict) -> dict:
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    out = {"leverage_max": 2.75, "interest_cover_min": 3.5, "undrawn_bn": None, "testing_frequency": "semi-annual"}
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


def _covenant_risk_score(
    current_breach: bool,
    stress_breach: bool,
    leverage_headroom_pct: float | None,
    coverage_headroom_pct: float | None,
) -> float:
    """Covenant risk score: current breach=10, stress breach=30, headroom<10%=40, <20%=60, else 80+."""
    if current_breach:
        return 10.0
    if stress_breach:
        return 30.0
    min_headroom = None
    if leverage_headroom_pct is not None and coverage_headroom_pct is not None:
        min_headroom = min(leverage_headroom_pct, coverage_headroom_pct)
    elif leverage_headroom_pct is not None:
        min_headroom = leverage_headroom_pct
    elif coverage_headroom_pct is not None:
        min_headroom = coverage_headroom_pct
    if min_headroom is not None:
        if min_headroom < 0:
            return 10.0
        if min_headroom < 10:
            return 40.0
        if min_headroom < 20:
            return 60.0
    return 85.0


def run_covenant_engine(
    notes_json: dict | None,
    nd_ebitda: float | None,
    interest_cover: float | None,
    undrawn_facilities: float | None,
    stress_scenarios: dict | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"section_name": "Covenants & Headroom", "key_metrics": {}, "score": 70.0, "section_rating": "Adequate", "risk_flags": [], "evidence_notes": ["Note 48: Going concern", "Note 43.4.3: Covenant terms"], "llm_commentary": ""}
    parsed = _parse_covenants(notes_json or {})
    lev_max = parsed["leverage_max"]
    ic_min = parsed["interest_cover_min"]
    block["key_metrics"]["covenant_leverage_max"] = lev_max
    block["key_metrics"]["covenant_interest_cover_min"] = ic_min
    block["key_metrics"]["current_nd_ebitda"] = nd_ebitda
    block["key_metrics"]["current_interest_cover"] = interest_cover
    block["key_metrics"]["undrawn_facilities"] = undrawn_facilities or parsed["undrawn_bn"]

    # Leverage headroom: (covenant_max - current) / covenant_max
    lev_headroom_pct = None
    if nd_ebitda is not None and lev_max and lev_max > 0:
        lev_headroom_pct = 100 * (lev_max - nd_ebitda) / lev_max
        block["key_metrics"]["leverage_headroom_pct"] = round(lev_headroom_pct, 1)
    # Coverage headroom: (current - covenant_min) / covenant_min
    cov_headroom_pct = None
    if interest_cover is not None and ic_min and ic_min > 0:
        cov_headroom_pct = 100 * (interest_cover - ic_min) / ic_min
        block["key_metrics"]["coverage_headroom_pct"] = round(cov_headroom_pct, 1)

    lev_breach = nd_ebitda is not None and nd_ebitda >= lev_max
    ic_breach = interest_cover is not None and interest_cover < ic_min
    current_breach = lev_breach or ic_breach

    if lev_breach:
        block["risk_flags"].append("Covenant breach: ND/EBITDA at or above limit")
        block["key_metrics"]["leverage_breach"] = True
        block["key_metrics"]["leverage_breach_distance"] = round(nd_ebitda - lev_max, 2)
    else:
        block["key_metrics"]["leverage_breach"] = False
    if ic_breach:
        block["risk_flags"].append("Covenant breach: Interest cover below minimum")
        block["key_metrics"]["interest_cover_breach"] = True
        block["key_metrics"]["interest_cover_breach_distance"] = round(ic_min - interest_cover, 2)
    else:
        block["key_metrics"]["interest_cover_breach"] = False

    # Stress headroom: check stressed ND/EBITDA and interest cover vs covenants
    stress_breach = False
    if stress_scenarios:
        for sc in (stress_scenarios or {}).values():
            nd_s = sc.get("net_debt_to_ebitda_stressed")
            ic_s = sc.get("interest_cover_stressed")
            if nd_s is not None and nd_s >= lev_max:
                stress_breach = True
                block["key_metrics"]["stress_leverage_breach"] = True
            if ic_s is not None and ic_s < ic_min:
                stress_breach = True
                block["key_metrics"]["stress_coverage_breach"] = True
            if stress_breach:
                break

    headroom_score = _covenant_risk_score(
        current_breach, stress_breach, lev_headroom_pct, cov_headroom_pct
    )
    section_score = max(0, min(100, headroom_score))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    return block

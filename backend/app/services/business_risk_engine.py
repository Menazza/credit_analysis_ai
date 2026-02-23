"""Business Risk Engine - section-based. Extract -> score -> evidence."""
from __future__ import annotations
import re
from datetime import date
from typing import Any
from app.services.financial_engine import get_fact, compute_ebitda
from app.services.trend_engine import run_trend_engine
from app.core.section_schema import score_to_rating

def _extract_segment_info(notes: dict) -> list[str]:
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    segments = []
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:8000]
        if "segment" not in text.lower() and "revenue" not in text.lower():
            continue
        for m in re.finditer(r"(?:South Africa|Rest of Africa|Retail|Wholesale|Trading|Other)[^\d]{0,30}", text, re.I):
            seg = m.group(0).strip().rstrip(":")
            if len(seg) > 2 and seg not in segments:
                segments.append(seg)
    return segments[:10]

def _extract_geographic_exposure(notes: dict) -> list[str]:
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    regions = []
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:4000]
        if "geographic" in text.lower() or "segment" in text.lower():
            for m in re.finditer(r"(?:South Africa|Nigeria|Namibia|Botswana|Lesotho|Mozambique|Zambia|Malawi|Angola)", text, re.I):
                r = m.group(0)
                if r not in regions:
                    regions.append(r)
    return regions[:8]

def run_business_risk_engine(facts: dict[tuple[str, date], float], periods: list[date], notes_json: dict | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {"section_name": "Business Risk Assessment", "key_metrics": {}, "score": 50.0, "section_rating": "Adequate", "risk_flags": [], "evidence_notes": [], "llm_commentary": ""}
    notes = notes_json or {}
    trend = run_trend_engine(facts, periods)
    growth = trend.get("growth_diagnostics") or {}
    periods_sorted = sorted(periods, reverse=True)
    latest = periods_sorted[0] if periods_sorted else None
    if not latest:
        return block
    rev = get_fact(facts, "revenue", latest) or 0
    ebitda = compute_ebitda(facts, latest) or 0
    margin = 100.0 * ebitda / rev if rev and rev > 0 else None
    rev_growth = growth.get("revenue_growth_pct")
    ebitda_growth = growth.get("ebitda_growth_pct")
    margin_delta_bps = growth.get("margin_delta_bps")
    block["key_metrics"] = {"revenue": round(rev, 2), "revenue_growth_pct": round(rev_growth, 1) if rev_growth is not None else None, "ebitda_growth_pct": round(ebitda_growth, 1) if ebitda_growth is not None else None, "ebitda_margin_pct": round(margin, 1) if margin is not None else None, "margin_delta_bps": round(margin_delta_bps, 0) if margin_delta_bps is not None else None}
    segments = _extract_segment_info(notes)
    regions = _extract_geographic_exposure(notes)
    if segments:
        block["key_metrics"]["segment_count"] = len(segments)
        block["evidence_notes"].append("Operating segments (Note 2/26): " + str(len(segments)) + " identified")
    if regions:
        block["key_metrics"]["geographic_regions"] = regions
        block["evidence_notes"].append("Geographic exposure: " + ", ".join(regions[:5]))
    stability_score = 50.0
    if rev_growth is not None:
        if -5 <= (rev_growth or 0) <= 15:
            stability_score += 15
        elif -10 <= (rev_growth or 0) <= 25:
            stability_score += 5
        elif abs(rev_growth or 0) > 30:
            stability_score -= 20
            block["risk_flags"].append("High revenue volatility")
    if ebitda_growth is not None and (ebitda_growth or 0) < -10:
        stability_score -= 15
        block["risk_flags"].append("EBITDA decline")
    diversification_score = 70.0 if len(segments) >= 3 else (60.0 if len(segments) >= 2 else 50.0)
    if len(segments) == 1:
        diversification_score = 40.0
        block["risk_flags"].append("Limited segment concentration")
    margin_score = 65.0 if margin and margin >= 5 else (55.0 if margin and margin >= 2 else 50.0)
    if margin is not None and margin < 0:
        margin_score = 25.0
        block["risk_flags"].append("Negative EBITDA margin")
    block["evidence_notes"].extend(["Note 2: Operating segments", "Note 26: Revenue", "Note 43: Risk management"])
    section_score = max(0, min(100, stability_score * 0.4 + diversification_score * 0.35 + margin_score * 0.25))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    block["period"] = latest.isoformat()
    return block

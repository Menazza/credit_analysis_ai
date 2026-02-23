"""Financial Performance Engine - section-based. Extract -> score."""
from __future__ import annotations
from datetime import date
from typing import Any
from app.services.financial_engine import get_fact, compute_ebitda
from app.services.trend_engine import run_trend_engine
from app.core.section_schema import score_to_rating

def run_performance_engine(facts: dict[tuple[str, date], float], periods: list[date]) -> dict[str, Any]:
    block: dict[str, Any] = {"section_name": "Financial Performance Analysis", "key_metrics": {}, "score": 50.0, "section_rating": "Adequate", "risk_flags": [], "evidence_notes": ["Note 27: Depreciation", "Note 30: Operating expenses", "Note 33: Finance costs", "Note 34: Tax"], "llm_commentary": ""}
    trend = run_trend_engine(facts, periods)
    growth = trend.get("growth_diagnostics") or {}
    quality = trend.get("quality_diagnostics") or {}
    periods_sorted = sorted(periods, reverse=True)
    latest = periods_sorted[0] if periods_sorted else None
    if not latest:
        return block
    rev = get_fact(facts, "revenue", latest) or 0
    op = get_fact(facts, "operating_profit", latest)
    pat = get_fact(facts, "profit_after_tax", latest)
    cfo = get_fact(facts, "net_cfo", latest)
    capex = get_fact(facts, "capex", latest)
    ebitda = compute_ebitda(facts, latest) or 0
    margin = 100.0 * ebitda / rev if rev and rev > 0 else None
    rev_growth = growth.get("revenue_growth_pct")
    ebitda_growth = growth.get("ebitda_growth_pct")
    pat_growth = growth.get("pat_growth_pct")
    margin_delta_bps = growth.get("margin_delta_bps")
    cfo_to_ebitda = quality.get("cfo_to_ebitda")
    fcf = (cfo or 0) - (capex or 0)
    fcf_conversion = fcf / ebitda if ebitda and ebitda != 0 else None
    block["key_metrics"] = {"revenue": round(rev, 2), "revenue_growth_pct": round(rev_growth, 1) if rev_growth is not None else None, "ebitda_growth_pct": round(ebitda_growth, 1) if ebitda_growth is not None else None, "pat_growth_pct": round(pat_growth, 1) if pat_growth is not None else None, "ebitda_margin_pct": round(margin, 1) if margin is not None else None, "operating_profit": round(op, 2) if op is not None else None, "profit_after_tax": round(pat, 2) if pat is not None else None, "cfo_to_ebitda": round(cfo_to_ebitda, 2) if cfo_to_ebitda is not None else None, "fcf_conversion": round(fcf_conversion, 2) if fcf_conversion is not None else None}
    block["by_period"] = {pe.isoformat(): {"revenue": get_fact(facts, "revenue", pe), "ebitda": compute_ebitda(facts, pe)} for pe in periods_sorted[:3]}
    block["period"] = latest.isoformat()
    profit_score = 65.0 if margin and margin >= 5 else (55.0 if margin and margin >= 2 else 50.0)
    if op is not None and rev and op < 0:
        profit_score = 25.0
        block["risk_flags"].append("Operating loss")
    quality_score = 65.0 if cfo_to_ebitda is not None and cfo_to_ebitda >= 0.5 else (35.0 if cfo_to_ebitda is not None and cfo_to_ebitda < 0 else 50.0)
    if cfo_to_ebitda is not None and cfo_to_ebitda < 0:
        block["risk_flags"].append("CFO below EBITDA")
    stability_score = 70.0 if rev_growth is not None and 0 <= (rev_growth or 0) <= 20 else 50.0
    if ebitda_growth is not None and (ebitda_growth or 0) < -15:
        stability_score -= 25
        block["risk_flags"].append("Material EBITDA decline")
    section_score = max(0, min(100, profit_score * 0.4 + quality_score * 0.35 + stability_score * 0.25))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    return block

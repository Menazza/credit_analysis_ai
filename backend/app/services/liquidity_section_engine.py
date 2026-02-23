"""
Liquidity Section Engine - wraps liquidity metrics in section block format.
"""
from __future__ import annotations
from datetime import date
from typing import Any

from app.services.liquidity_engine import run_liquidity_engine
from app.services.financial_engine import get_fact
from app.core.section_schema import score_to_rating


def run_liquidity_section_engine(
    facts: dict[tuple[str, date], float],
    periods: list[date],
    committed_facilities: dict[str, float] | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "section_name": "Cash Flow & Liquidity",
        "key_metrics": {},
        "score": 50.0,
        "section_rating": "Adequate",
        "risk_flags": [],
        "evidence_notes": ["Note 38: Cash flows", "Note 21: Borrowings", "Note 20: Lease liabilities", "Note 48: Going concern"],
        "llm_commentary": "",
    }
    liquidity = run_liquidity_engine(facts, periods, committed_facilities)
    periods_sorted = sorted(periods, reverse=True)
    latest = periods_sorted[0] if periods_sorted else None
    if not latest:
        return block

    lp = liquidity.get("by_period", {}).get(latest.isoformat(), {})
    cfo = get_fact(facts, "net_cfo", latest)
    capex = get_fact(facts, "capex", latest)
    fcf = (cfo or 0) - (capex or 0) if cfo is not None else None

    block["key_metrics"] = {
        "net_cfo": round(cfo, 2) if cfo is not None else None,
        "capex": round(capex, 2) if capex is not None else None,
        "fcf": round(fcf, 2) if fcf is not None else None,
        "current_ratio": lp.get("current_ratio"),
        "quick_ratio": lp.get("quick_ratio"),
        "cash": lp.get("cash"),
        "st_debt": lp.get("st_debt"),
        "st_debt_to_cash": lp.get("st_debt_to_cash"),
        "liquidity_runway_months": lp.get("liquidity_runway_months"),
        "undrawn_facilities": lp.get("undrawn_facilities"),
        "lease_adjusted_liquidity": lp.get("lease_adjusted_liquidity"),
    }
    block["by_period"] = liquidity.get("by_period", {})
    block["period"] = latest.isoformat()

    adequacy_score = 50.0
    cr = lp.get("current_ratio")
    cash = lp.get("cash") or 0
    st_debt = lp.get("st_debt") or 0

    if cr is not None:
        if cr >= 1.5:
            adequacy_score = 80
        elif cr >= 1.0:
            adequacy_score = 65
        elif cr >= 0.8:
            adequacy_score = 50
        else:
            adequacy_score = 30
            block["risk_flags"].append("Current ratio below 0.8x")
    if cash < 0:
        adequacy_score = min(adequacy_score, 25)
        block["risk_flags"].append("Negative cash position")
    elif st_debt > 0 and cash > 0:
        stc = lp.get("st_debt_to_cash")
        if stc is not None and stc > 2:
            block["risk_flags"].append("ST debt/cash elevated")

    conversion_score = 50.0
    if cfo is not None and cfo > 0:
        conversion_score = 70
    elif cfo is not None and cfo < 0:
        conversion_score = 30
        block["risk_flags"].append("Negative CFO")

    runway = lp.get("liquidity_runway_months")
    if runway is not None and runway >= 12:
        adequacy_score = min(100, adequacy_score + 10)
    if st_debt <= 0 and cash > 0:
        adequacy_score = min(85, adequacy_score + 15)

    section_score = adequacy_score * 0.6 + conversion_score * 0.4
    section_score = max(0, min(100, section_score))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    return block

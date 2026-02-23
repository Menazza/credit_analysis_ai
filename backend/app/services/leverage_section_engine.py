"""
Leverage Section Engine - wraps leverage metrics in section block format.
Net debt, debt/capital, interest cover, fixed charge cover with scoring.
"""
from __future__ import annotations
from datetime import date
from typing import Any

from app.services.leverage_engine import run_leverage_engine
from app.core.section_schema import SectionBlock, score_to_rating


def run_leverage_section_engine(
    facts: dict[tuple[str, date], float],
    periods: list[date],
) -> SectionBlock:
    """
    Leverage & capital structure assessment. Output: section block.
    Notes: Note 21 (Borrowings), Note 20 (Lease liabilities), Note 39 (Contingent liabilities).
    """
    block: SectionBlock = {
        "section_name": "Leverage & Capital Structure",
        "key_metrics": {},
        "score": 50.0,
        "section_rating": "Adequate",
        "risk_flags": [],
        "evidence_notes": ["Note 21: Borrowings", "Note 20: Lease liabilities", "Note 39: Contingent liabilities"],
        "llm_commentary": "",
    }
    leverage = run_leverage_engine(facts, periods)
    periods_sorted = sorted(periods, reverse=True)
    latest = periods_sorted[0] if periods_sorted else None
    if not latest:
        return block

    lp = leverage.get("by_period", {}).get(latest.isoformat(), {})
    block["key_metrics"] = {k: v for k, v in lp.items()}
    block["by_period"] = leverage.get("by_period", {})
    block["period"] = latest.isoformat()

    nd_incl = lp.get("net_debt_incl_leases")
    nd_ebitda = lp.get("net_debt_to_ebitda_incl_leases")
    ic = lp.get("ebitda_to_interest")
    debt_cap = lp.get("debt_to_capital")

    # Leverage strength (net debt/EBITDA)
    leverage_score = 50.0
    if nd_ebitda is not None:
        if nd_ebitda < 0:  # Net cash
            leverage_score = 90
        elif nd_ebitda <= 1.0:
            leverage_score = 80
        elif nd_ebitda <= 2.0:
            leverage_score = 65
        elif nd_ebitda <= 3.0:
            leverage_score = 50
        elif nd_ebitda <= 4.0:
            leverage_score = 35
            block["risk_flags"].append("ND/EBITDA above 3x")
        else:
            leverage_score = 20
            block["risk_flags"].append("High leverage (ND/EBITDA > 4x)")
    elif nd_incl is not None and nd_incl < 0:
        leverage_score = 85

    # Coverage adequacy
    coverage_score = 50.0
    if ic is not None:
        if ic >= 5.0:
            coverage_score = 90
        elif ic >= 3.5:
            coverage_score = 75
        elif ic >= 2.5:
            coverage_score = 60
        elif ic >= 2.0:
            coverage_score = 45
            block["risk_flags"].append("Interest cover below 2.5x")
        else:
            coverage_score = 25
            block["risk_flags"].append("Interest cover below 2x")

    section_score = leverage_score * 0.5 + coverage_score * 0.5
    section_score = max(0, min(100, section_score))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    return block

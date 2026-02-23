"""Section-Based Analysis Orchestrator. Runs 8 engines -> aggregation -> commentary."""
from __future__ import annotations
from datetime import date
from typing import Any

def run_section_based_analysis(facts: dict[tuple[str, date], float], periods: list[date], notes_json: dict | None = None, committed_facilities: dict[str, float] | None = None, company_name: str = "", rating_grade_override: str | None = None) -> dict[str, Any]:
    from app.services.financial_engine import run_engine
    from app.services.business_risk_engine import run_business_risk_engine
    from app.services.performance_engine import run_performance_engine
    from app.services.liquidity_section_engine import run_liquidity_section_engine
    from app.services.leverage_section_engine import run_leverage_section_engine
    from app.services.notes_validation_engine import run_accounting_quality_engine
    from app.services.stress_section_engine import run_stress_section_engine
    from app.services.covenant_engine import run_covenant_engine
    from app.services.rating_aggregation_engine import run_rating_aggregation
    from app.services.section_commentary import add_section_commentary

    periods_sorted = sorted(periods, reverse=True)
    latest = periods_sorted[0] if periods_sorted else None
    facts_by_period_iso = {p.isoformat(): {k[0]: v for (k, v) in facts.items() if k[1] == p} for p in periods}
    financial = run_engine(facts, periods)
    ebitda = financial.get("ebitda", {}).get(latest.isoformat()) if latest else None

    section_blocks: dict[str, dict[str, Any]] = {}
    section_blocks["business_risk"] = run_business_risk_engine(facts, periods, notes_json)
    section_blocks["financial_performance"] = run_performance_engine(facts, periods)
    section_blocks["liquidity"] = run_liquidity_section_engine(facts, periods, committed_facilities)
    section_blocks["leverage"] = run_leverage_section_engine(facts, periods)
    section_blocks["accounting_quality"] = run_accounting_quality_engine(notes_json, facts_by_period_iso, ebitda)
    section_blocks["stress"] = run_stress_section_engine(facts, periods)
    lev_block = section_blocks.get("leverage", {}).get("key_metrics") or {}
    liq_block = section_blocks.get("liquidity", {}).get("key_metrics") or {}
    section_blocks["covenants"] = run_covenant_engine(notes_json, lev_block.get("net_debt_to_ebitda_incl_leases"), lev_block.get("ebitda_to_interest"), liq_block.get("undrawn_facilities"))
    stress_raw = section_blocks.get("stress", {}).get("key_metrics", {}).get("scenarios", {})

    aggregation = run_rating_aggregation(section_blocks, covenant_block=section_blocks.get("covenants"), stress_output={"scenarios": stress_raw}, notes_json=notes_json)
    if rating_grade_override:
        aggregation["rating_grade"] = rating_grade_override
    add_section_commentary(section_blocks, aggregation, company_name)

    return {"audit": {"periods": [p.isoformat() for p in periods]}, "section_blocks": section_blocks, "aggregation": aggregation, "financial": financial, "facts_by_period": facts_by_period_iso}

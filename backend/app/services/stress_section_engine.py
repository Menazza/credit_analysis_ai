"""Stress Testing Section Engine - section block with scoring."""
from __future__ import annotations
from datetime import date
from typing import Any
from app.services.stress_engine import run_stress_engine
from app.core.section_schema import score_to_rating

def run_stress_section_engine(facts: dict[tuple[str, date], float], periods: list[date]) -> dict[str, Any]:
    block: dict[str, Any] = {"section_name": "Stress Testing & Downside Analysis", "key_metrics": {}, "score": 50.0, "section_rating": "Adequate", "risk_flags": [], "evidence_notes": [], "llm_commentary": ""}
    stress = run_stress_engine(facts, periods)
    scenarios = stress.get("scenarios") or {}
    block["key_metrics"] = {"scenarios": scenarios}
    block["by_period"] = scenarios
    resilience_score = 70.0
    for name, sc in scenarios.items():
        ic = sc.get("interest_cover_stressed")
        nd = sc.get("net_debt_to_ebitda_stressed")
        if ic is not None and ic < 2.0:
            resilience_score -= 25
            block["risk_flags"].append(name + ": Interest cover below 2x")
        elif ic is not None and ic < 2.5:
            resilience_score -= 10
        if nd is not None and nd > 3.0:
            resilience_score -= 15
            block["risk_flags"].append(name + ": ND/EBITDA above 3x")
        cash_after = sc.get("cash_after_shock")
        if cash_after is not None and cash_after < 0:
            resilience_score -= 20
            block["risk_flags"].append(name + ": Cash negative after shock")
    section_score = max(0, min(100, resilience_score))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    block["period"] = list(scenarios.values())[0].get("period", "") if scenarios else ""
    return block

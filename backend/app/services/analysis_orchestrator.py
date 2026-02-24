"""
Analysis Orchestrator - runs full credit decision engine pipeline.
Section-based: 8 engines -> rating aggregation -> memo.
Legacy: financial, trend, liquidity, leverage, stress, risk, rating, commentary.
"""
from __future__ import annotations
from datetime import date
from typing import Any

def run_full_analysis(
    facts: dict[tuple[str, date], float],
    periods: list[date],
    notes_json: dict | None = None,
    committed_facilities: dict[str, float] | None = None,
    fs_version: str = "",
    mapping_version: str = "",
    company_name: str = "",
    rating_grade_override: str | None = None,
) -> dict[str, Any]:
    """
    Run section-based analysis (8 engines, weighted rating). Outputs section_blocks + aggregation.

    rating_grade_override: When set (e.g. from legacy run_rating), overrides the section-based
    aggregate rating. Used when the memo should display the model-driven rating.
    """
    from app.services.section_orchestrator import run_section_based_analysis

    out = run_section_based_analysis(
        facts=facts,
        periods=periods,
        notes_json=notes_json,
        committed_facilities=committed_facilities,
        company_name=company_name,
        rating_grade_override=rating_grade_override,
    )
    out["audit"]["fs_version"] = fs_version
    out["audit"]["mapping_version"] = mapping_version
    out["rating"] = {"rating_grade": out["aggregation"].get("rating_grade")}
    return out

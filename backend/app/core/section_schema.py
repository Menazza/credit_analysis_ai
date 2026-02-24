"""
Section block schema for institutional credit analysis.
Each section engine outputs a structured block; LLM interprets only.
"""
from __future__ import annotations
from typing import Any, TypedDict

SECTION_RATINGS = ("Strong", "Adequate", "Weak")

# Section weights for aggregate rating (must sum to 100).
# stress and covenants are computed but governance-only (e.g. notch caps); not in weighted score.
SECTION_WEIGHTS = {
    "business_risk": 25,
    "financial_performance": 25,
    "liquidity": 20,
    "leverage": 20,
    "accounting_quality": 10,
}


def score_to_rating(score: float) -> str:
    """Map 0-100 score to Strong/Adequate/Weak."""
    if score >= 70:
        return "Strong"
    if score >= 50:
        return "Adequate"
    return "Weak"


def rating_to_score(rating: str) -> float:
    """Map Strong/Adequate/Weak to midpoint score for aggregation."""
    return {"Strong": 80.0, "Adequate": 60.0, "Weak": 35.0}.get(rating, 50.0)


class SectionBlock(TypedDict, total=False):
    """Output shape for each section engine."""
    section_name: str
    key_metrics: dict[str, Any]
    score: float
    section_rating: str
    risk_flags: list[str]
    evidence_notes: list[str]
    llm_commentary: str
    period: str
    by_period: dict[str, Any]

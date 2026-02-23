"""Rating Aggregation Engine - weighted section scores -> final rating."""
from __future__ import annotations
from typing import Any
from app.core.section_schema import SECTION_WEIGHTS, score_to_rating, rating_to_score

RATING_BANDS = [
    (85, "AAA"),
    (80, "AA+"),
    (75, "AA"),
    (70, "AA-"),
    (65, "A+"),
    (60, "A"),
    (55, "A-"),
    (50, "BBB+"),
    (45, "BBB"),
    (40, "BBB-"),
    (35, "BB+"),
    (30, "BB"),
    (25, "BB-"),
    (20, "B+"),
    (15, "B"),
    (10, "B-"),
    (0, "CCC"),
]

def _score_to_grade(score: float) -> str:
    for threshold, grade in RATING_BANDS:
        if score >= threshold:
            return grade
    return "CCC"

def run_rating_aggregation(section_blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    weights = SECTION_WEIGHTS
    weighted_sum = 0.0
    total_weight = 0
    breakdown = {}
    for section_key, w in weights.items():
        block = section_blocks.get(section_key)
        if not block:
            continue
        score = block.get("score", 50.0)
        if not isinstance(score, (int, float)):
            score = 50.0
        weighted_sum += score * w
        total_weight += w
        breakdown[section_key] = {"score": score, "rating": block.get("section_rating", "Adequate"), "weight": w}
    if total_weight == 0:
        agg_score = 50.0
    else:
        agg_score = weighted_sum / total_weight
    grade = _score_to_grade(agg_score)
    return {
        "aggregate_score": round(agg_score, 1),
        "rating_grade": grade,
        "section_breakdown": breakdown,
        "section_blocks": section_blocks,
    }

"""Rating Aggregation Engine - weighted section scores -> final rating."""
from __future__ import annotations
from typing import Any
from app.core.section_schema import SECTION_WEIGHTS, score_to_rating, rating_to_score

def run_rating_aggregation(section_blocks: dict[str, dict[str, Any]], covenant_block: dict | None = None, stress_output: dict | None = None, notes_json: dict | None = None) -> dict[str, Any]:
    from app.core.rating_governance import apply_governance

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
    gov = apply_governance(agg_score, section_blocks, covenant_block, stress_output, notes_json)
    return {
        "aggregate_score": round(agg_score, 1),
        "rating_grade": gov["final_grade"],
        "base_grade": gov["base_grade"],
        "hard_cap_grade": gov.get("hard_cap_grade"),
        "governance_rules": gov["applied_rules"],
        "section_breakdown": breakdown,
        "section_blocks": section_blocks,
    }

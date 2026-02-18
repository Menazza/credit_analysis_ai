"""
Rating & scorecard engine — config-driven, deterministic.
Uses rating_config.json: quantitative bands + qualitative factors + overrides.
Outputs: internal grade, PD band, rationale, rating drivers.
"""
import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent.parent / "core" / "rating_config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def score_quantitative(config: dict, metrics: dict[str, float]) -> tuple[float, dict]:
    q = config.get("quantitative", {})
    weight = q.get("weight", 0.65)
    aggregation = q.get("aggregation", "weighted_average")
    total_weight = 0.0
    weighted_sum = 0.0
    breakdown = {}
    for m in q.get("metrics", []):
        key = m["key"]
        w = m["weight"]
        direction = m.get("direction", "higher_is_better")
        bands = m.get("bands", [])
        value = metrics.get(key)
        if value is None:
            continue
        score = None
        if direction == "lower_is_better":
            bands_sorted = sorted(bands, key=lambda b: b.get("max", 0))
            for band in bands_sorted:
                if value <= band["max"]:
                    score = band["score"]
                    break
            if score is None:
                score = bands_sorted[-1]["score"] if bands_sorted else 50
        else:
            bands_sorted = sorted(bands, key=lambda b: b.get("min", 0), reverse=True)
            for band in bands_sorted:
                if value >= band["min"]:
                    score = band["score"]
                    break
            if score is None:
                score = bands_sorted[-1]["score"] if bands_sorted else 50
        if score is not None:
            weighted_sum += score * w
            total_weight += w
            breakdown[key] = {"value": value, "score": score, "weight": w}
    if total_weight == 0:
        return 0.0, breakdown
    return (weighted_sum / total_weight) * weight, breakdown


def score_qualitative(config: dict, factors: dict[str, str]) -> float:
    q = config.get("qualitative", {})
    weight = q.get("weight", 0.35)
    total = 0.0
    total_w = 0.0
    for f in q.get("factors", []):
        key = f["key"]
        w = f["weight"]
        levels = f.get("levels", {})
        level = factors.get(key, "MED")
        s = levels.get(level, 65)
        total += s * w
        total_w += w
    if total_w == 0:
        return 0.0
    return (total / total_w) * weight


def score_to_grade(config: dict, total_score: float) -> str:
    scales = config.get("scales", {})
    grades = scales.get("grades", ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"])
    internal = scales.get("internal_scores", {})
    for g in grades:
        lo, hi = internal.get(g, [0, 100])
        if lo <= total_score <= hi:
            return g
    return config.get("outputs", {}).get("default_grade", "BBB")


def apply_overrides(config: dict, grade: str, overrides_context: dict) -> str:
    caps = config.get("overrides", {}).get("hard_caps", [])
    for cap in caps:
        cond = cap.get("if", {})
        if all(overrides_context.get(k) == v for k, v in cond.items()):
            cap_grade = cap.get("cap_grade")
            if cap_grade:
                return cap_grade
    return grade


def run_rating(
    metrics: dict[str, float],
    qualitative: dict[str, str] | None = None,
    overrides_context: dict | None = None,
) -> dict[str, Any]:
    config = load_config()
    qual = qualitative or {}
    overrides_context = overrides_context or {}
    quant_score, quant_breakdown = score_quantitative(config, metrics)
    qual_score = score_qualitative(config, qual)
    total_score = quant_score + qual_score
    grade = score_to_grade(config, total_score)
    grade = apply_overrides(config, grade, overrides_context)
    outputs = config.get("outputs", {})
    pd_mapping = outputs.get("pd_mapping", {})
    pd_band = pd_mapping.get(grade)
    return {
        "rating_grade": grade,
        "total_score": round(total_score, 2),
        "quantitative_score": round(quant_score, 2),
        "qualitative_score": round(qual_score, 2),
        "score_breakdown": quant_breakdown,
        "pd_band": pd_band,
        "rationale": {
            "quantitative_breakdown": quant_breakdown,
            "qualitative_factors": qual,
        },
    }

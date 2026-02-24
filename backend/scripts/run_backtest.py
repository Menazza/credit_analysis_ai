#!/usr/bin/env python3
"""
Track 6B: Backtest harness - run engine on gold set, distribution of grades, comparison to known outcomes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter
from datetime import date


def run_backtest(gold_dir: str | Path | None = None) -> dict:
    """
    Run financial + rating engine on gold extraction outputs.
    Returns: {grades: {grade: count}, comparisons: [...], summary: {...}}
    """
    gold_dir = Path(gold_dir or Path(__file__).parent.parent / "tests" / "gold")
    if not gold_dir.exists():
        return {"error": f"Gold dir not found: {gold_dir}", "grades": {}, "comparisons": []}

    from app.services.mapping_pipeline import run_mapping
    from app.services.financial_engine import run_engine
    from app.services.rating_engine import run_rating
    from app.services.extraction_loader import load_extraction_from_file, extraction_to_flat_rows

    grades: list[str] = []
    comparisons: list[dict] = []
    extraction_files = list(gold_dir.glob("**/extraction*.xlsx")) + list(gold_dir.glob("**/statements*.xlsx"))
    if not extraction_files:
        extraction_files = list(gold_dir.glob("**/*.xlsx"))
    if not extraction_files:
        return {"error": "No extraction files in gold dir", "grades": {}, "comparisons": []}

    for fpath in extraction_files[:20]:
        try:
            extraction = load_extraction_from_file(str(fpath))
            sheet_to_type = {s: s.split("_")[0] for s in extraction.keys()}
            facts = run_mapping(
                excel_key="",
                company_id="backtest",
                extraction_override=extraction,
            )
            if isinstance(facts, tuple):
                facts = facts[0]
            if not facts:
                continue
            facts_dict = {(f["canonical_key"], f["period_end"]): f["value_base"] for f in facts}
            periods = sorted({f["period_end"] for f in facts}, reverse=True)
            if not periods:
                continue
            engine_out = run_engine(facts_dict, periods)
            latest = periods[0]
            metrics = {k: (v.get(latest.isoformat() if hasattr(latest, "isoformat") else str(latest)) if isinstance(v, dict) else v) for k, v in engine_out.items()}
            metrics = {k: v for k, v in metrics.items() if v is not None}
            result = run_rating(metrics)
            grade = result.get("rating_grade", "N/A")
            grades.append(grade)
            comparisons.append({
                "file": fpath.name,
                "grade": grade,
                "facts_count": len(facts),
                "periods": [str(p) for p in periods[:3]],
            })
        except Exception as e:
            comparisons.append({"file": fpath.name, "error": str(e)})

    dist = dict(Counter(grades))
    return {
        "grades": dist,
        "total_runs": len(grades),
        "comparisons": comparisons,
        "summary": {
            "unique_grades": len(dist),
            "most_common": dist and max(dist.items(), key=lambda x: x[1]),
        },
    }


if __name__ == "__main__":
    out = run_backtest()
    print(json.dumps(out, indent=2))

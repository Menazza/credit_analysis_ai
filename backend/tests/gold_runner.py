"""
Gold document test runner — deterministic regression for credit analysis pipeline.

Run: mapping → validator → engine → rating → memo, compare to snapshots.
Exit 0 = PASS, non-zero = FAIL.

Usage:
  python -m tests.gold_runner                    # Run all gold docs
  python -m tests.gold_runner tests/gold/shoprite_2025  # Run one
  python -m tests.gold_runner --bootstrap tests/gold/shoprite_2025 --extraction path/to/statements.xlsx --notes path/to/notes.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import date
from uuid import UUID

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend))

GOLD_ROOT = Path(__file__).resolve().parent / "gold"
TEST_COMPANY_ID = "00000000-0000-0000-0000-000000000001"


def _facts_to_snapshot(facts: list[dict]) -> list[dict]:
    """Normalize fact dicts for snapshot (exclude company_id, order by key+period)."""
    out = []
    for f in facts:
        pe = f.get("period_end")
        pe_str = pe.isoformat() if hasattr(pe, "isoformat") else str(pe)
        out.append({
            "canonical_key": f.get("canonical_key"),
            "period_end": pe_str,
            "value_base": round(float(f.get("value_base", 0)), 2),
        })
    out.sort(key=lambda x: (x["canonical_key"] or "", x["period_end"] or ""))
    return out


def _run_pipeline_for_gold(
    extraction_path: Path,
    notes_path: Path | None,
) -> tuple[list[dict], dict, dict, list[str]]:
    """Run mapping → engine → analysis → memo. Return (facts_snapshot, metrics, rating, memo_bullets)."""
    from app.services.extraction_loader import load_extraction_from_file
    from app.services.mapping_pipeline import run_mapping
    from app.services.financial_engine import run_engine
    from app.services.analysis_orchestrator import run_full_analysis
    from app.services.memo_composer import build_all_sections

    extraction = load_extraction_from_file(str(extraction_path))
    facts_rows = run_mapping("", TEST_COMPANY_ID, extraction_override=extraction)

    facts_dict: dict[tuple[str, date], float] = {}
    periods_set: set[date] = set()
    for r in facts_rows:
        pe = r["period_end"]
        facts_dict[(r["canonical_key"], pe)] = float(r["value_base"])
        periods_set.add(pe)
    periods = sorted(periods_set, reverse=True)[:5]

    engine_out = run_engine(facts_dict, periods)
    metrics = {}
    for mk, pv in (engine_out or {}).items():
        for pe_str, v in (pv or {}).items():
            pe = date.fromisoformat(pe_str) if isinstance(pe_str, str) else pe_str
            key = f"{mk}_{pe.isoformat()}"
            metrics[key] = round(float(v), 4) if v is not None else None
    metrics_sorted = dict(sorted(metrics.items()))

    notes_json = None
    if notes_path and notes_path.exists():
        notes_json = json.loads(notes_path.read_text(encoding="utf-8"))

    analysis = run_full_analysis(
        facts=facts_dict,
        periods=periods,
        notes_json=notes_json,
        company_name="Gold Test",
        rating_grade_override=None,
    )

    agg = analysis.get("aggregation") or {}
    rating = {
        "rating_grade": agg.get("rating_grade"),
        "aggregate_score": agg.get("aggregate_score"),
        "base_grade": agg.get("base_grade"),
        "hard_cap_grade": agg.get("hard_cap_grade"),
    }

    facts_by_period = {pe: {k: v for (k, p), v in facts_dict.items() if p == pe} for pe in periods}
    metric_by_period: dict[date, dict[str, float]] = {}
    for mk, pv in (engine_out or {}).items():
        for pe_str, v in (pv or {}).items():
            pe = date.fromisoformat(pe_str) if isinstance(pe_str, str) else pe_str
            if pe not in metric_by_period:
                metric_by_period[pe] = {}
            if v is not None:
                metric_by_period[pe][mk] = float(v)
    latest = periods[0] if periods else None
    key_metrics = metric_by_period.get(latest, {}) if latest else {}

    section_texts = build_all_sections(
        company_name="Gold Test",
        review_period_end=latest,
        rating_grade=rating.get("rating_grade"),
        recommendation="Maintain",
        facts_by_period=facts_by_period,
        metric_by_period=metric_by_period,
        key_metrics=key_metrics,
        notes_json=notes_json,
        analysis_output=analysis,
    )

    memo_bullets = []
    for sec_key, text in section_texts.items():
        for line in (text or "").split("\n"):
            line = line.strip()
            if line and (line.startswith("- ") or line.startswith("• ")):
                memo_bullets.append(f"{sec_key}: {line[:120]}")
    memo_bullets.sort()

    return _facts_to_snapshot(facts_rows), metrics_sorted, rating, memo_bullets


def _compare_snapshot(got: dict | list, expected_path: Path, label: str) -> list[str]:
    errs = []
    if not expected_path.exists():
        errs.append(f"{label}: snapshot missing at {expected_path}")
        return errs
    exp = json.loads(expected_path.read_text(encoding="utf-8"))
    if isinstance(got, dict) and isinstance(exp, dict):
        for k in set(got) | set(exp):
            g = got.get(k)
            e = exp.get(k)
            if isinstance(g, float) and isinstance(e, (int, float)):
                if abs(g - float(e)) > 1e-4:
                    errs.append(f"{label}.{k}: got {g} expected {e}")
            elif g != e:
                errs.append(f"{label}.{k}: got {g!r} expected {e!r}")
    elif got != exp:
        errs.append(f"{label}: output differs from snapshot")
    return errs


def _compare_facts(got: list[dict], expected_path: Path) -> list[str]:
    errs = []
    if not expected_path.exists():
        errs.append(f"normalized_facts: snapshot missing at {expected_path}")
        return errs
    exp = json.loads(expected_path.read_text(encoding="utf-8"))
    got_keys = {(r["canonical_key"], r["period_end"]) for r in got}
    exp_keys = {(r["canonical_key"], r["period_end"]) for r in exp}
    missing = exp_keys - got_keys
    extra = got_keys - exp_keys
    if missing:
        errs.append(f"normalized_facts: missing {len(missing)} expected keys")
    if extra:
        errs.append(f"normalized_facts: {len(extra)} extra keys")
    exp_map = {(r["canonical_key"], r["period_end"]): r["value_base"] for r in exp}
    for r in got:
        k = (r["canonical_key"], r["period_end"])
        if k in exp_map and abs(r["value_base"] - exp_map[k]) > 1e-2:
            errs.append(f"normalized_facts: {k} value {r['value_base']} != {exp_map[k]}")
    return errs


def _compare_memo_bullets(got: list[str], expected_path: Path) -> list[str]:
    errs = []
    if not expected_path.exists():
        errs.append(f"memo_bullets: snapshot missing at {expected_path}")
        return errs
    exp = json.loads(expected_path.read_text(encoding="utf-8"))
    if set(got) != set(exp):
        errs.append(f"memo_bullets: got {len(got)} bullets, expected {len(exp)}")
    return errs


def run_gold(gold_dir: Path) -> tuple[bool, list[str]]:
    """Run gold test for one document. Return (pass, errors)."""
    extraction_path = gold_dir / "extraction.xlsx"
    notes_path = gold_dir / "notes.json"
    expected_dir = gold_dir / "expected"

    if not extraction_path.exists():
        return False, [f"No extraction.xlsx at {extraction_path}"]

    try:
        facts_snap, metrics, rating, memo_bullets = _run_pipeline_for_gold(extraction_path, notes_path)
    except Exception as e:
        return False, [f"Pipeline error: {e}"]

    errs = []
    expected_dir.mkdir(parents=True, exist_ok=True)

    errs.extend(_compare_facts(facts_snap, expected_dir / "normalized_facts_snapshot.json"))
    errs.extend(_compare_snapshot(metrics, expected_dir / "metrics_snapshot.json", "metrics"))
    errs.extend(_compare_snapshot(rating, expected_dir / "rating_snapshot.json", "rating"))
    errs.extend(_compare_memo_bullets(memo_bullets, expected_dir / "memo_bullets_snapshot.json"))

    return len(errs) == 0, errs


def bootstrap(gold_dir: Path, extraction_path: Path, notes_path: Path | None) -> None:
    """Create gold folder and write snapshots from running pipeline."""
    gold_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(extraction_path, gold_dir / "extraction.xlsx")
    if notes_path and notes_path.exists():
        shutil.copy(notes_path, gold_dir / "notes.json")
    extraction_path_new = gold_dir / "extraction.xlsx"
    notes_path_new = gold_dir / "notes.json" if (gold_dir / "notes.json").exists() else None
    facts_snap, metrics, rating, memo_bullets = _run_pipeline_for_gold(extraction_path_new, notes_path_new)
    expected_dir = gold_dir / "expected"
    expected_dir.mkdir(parents=True, exist_ok=True)
    (expected_dir / "normalized_facts_snapshot.json").write_text(json.dumps(facts_snap, indent=2, default=str), encoding="utf-8")
    (expected_dir / "metrics_snapshot.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    (expected_dir / "rating_snapshot.json").write_text(json.dumps(rating, indent=2, default=str), encoding="utf-8")
    (expected_dir / "memo_bullets_snapshot.json").write_text(json.dumps(memo_bullets, indent=2, default=str), encoding="utf-8")
    print(f"Bootstrap complete: {gold_dir}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Gold document test runner")
    ap.add_argument("gold_path", nargs="?", default=str(GOLD_ROOT), help="Gold root or single doc folder")
    ap.add_argument("--bootstrap", action="store_true", help="Bootstrap: create snapshots from extraction")
    ap.add_argument("--extraction", help="Extraction Excel path (for bootstrap)")
    ap.add_argument("--notes", help="Notes JSON path (for bootstrap)")
    args = ap.parse_args()

    path = Path(args.gold_path)

    if args.bootstrap:
        if not args.extraction:
            print("--extraction required for bootstrap")
            return 1
        bootstrap(path, Path(args.extraction), Path(args.notes) if args.notes else None)
        return 0

    # Discover gold docs
    if (path / "extraction.xlsx").exists():
        gold_dirs = [path]
    else:
        gold_dirs = [d for d in path.iterdir() if d.is_dir() and (d / "extraction.xlsx").exists()]

    if not gold_dirs:
        print(f"No gold documents found under {path}")
        return 1

    all_ok = True
    for gold_dir in sorted(gold_dirs):
        ok, errs = run_gold(gold_dir)
        name = gold_dir.name
        if ok:
            print(f"PASS {name}")
        else:
            print(f"FAIL {name}")
            for e in errs:
                print(f"  {e}")
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

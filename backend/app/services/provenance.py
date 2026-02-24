"""
Provenance builder — attach audit trail from facts/metrics to analysis output.
Enables: click memo bullet → see exact facts + page refs.
Track 6C: Add version constants to analysis output.
"""
from __future__ import annotations
from datetime import date
from typing import Any

from app.core.versions import (
    MAPPING_RULES_VERSION,
    ENGINE_FORMULA_VERSION,
    RATING_MODEL_VERSION,
    MEMO_TEMPLATE_VERSION,
)


def add_provenance_to_analysis(
    analysis_output: dict[str, Any],
    facts_rows: list[Any],
    metric_rows: list[Any],
) -> None:
    """
    Attach provenance to analysis_output in-place.
    Adds: facts_provenance, metrics_provenance, section_citations.
    """
    facts_provenance = []
    for r in facts_rows:
        pe = r.period_end
        pe_str = pe.isoformat() if hasattr(pe, "isoformat") else str(pe)
        refs = getattr(r, "source_refs_json", None) or []
        facts_provenance.append({
            "canonical_key": r.canonical_key,
            "period_end": pe_str,
            "value_base": round(float(r.value_base), 2),
            "source_refs": refs,
        })
    facts_provenance.sort(key=lambda x: (x["canonical_key"], x["period_end"]))

    metrics_provenance = []
    for m in metric_rows:
        pe = m.period_end
        pe_str = pe.isoformat() if hasattr(pe, "isoformat") else str(pe) if pe else ""
        calc = getattr(m, "calc_trace_json", None) or []
        metrics_provenance.append({
            "metric_key": m.metric_key,
            "period_end": pe_str,
            "value": round(float(m.value), 4),
            "calc_trace": calc,
        })
    metrics_provenance.sort(key=lambda x: (x["metric_key"], x["period_end"]))

    section_citations: dict[str, dict[str, Any]] = {}
    blocks = analysis_output.get("section_blocks") or {}
    for sec_key, block in blocks.items():
        km = block.get("key_metrics") or {}
        evidence = block.get("evidence_notes") or []
        section_citations[sec_key] = {
            "metric_keys": list(km.keys()),
            "evidence_notes": evidence[:10],
        }

    analysis_output["provenance"] = {
        "facts": facts_provenance[:200],
        "metrics": metrics_provenance[:200],
        "section_citations": section_citations,
    }
    analysis_output["versions"] = {
        "mapping_rules": MAPPING_RULES_VERSION,
        "engine_formula": ENGINE_FORMULA_VERSION,
        "rating_model": RATING_MODEL_VERSION,
        "memo_template": MEMO_TEMPLATE_VERSION,
    }

"""
Phase 3: LLM-assisted mapping suggestions.
Proposals only — human review required before persistence.
"""
from __future__ import annotations

from typing import Any

from app.core.canonical_keys import CANONICAL_KEYS


def suggest_canonical_key(raw_label: str, context: str | None = None) -> dict[str, Any]:
    """
    Propose a canonical_key for raw_label. Returns {canonical_key, confidence, rationale}.
    Stub: returns best rule-based match; extend with LLM when configured.
    """
    from app.services.mapping_rules import map_raw_label

    canonical_key, method, _ = map_raw_label(raw_label)
    if canonical_key:
        return {
            "canonical_key": canonical_key,
            "confidence": 0.95 if method == "RULE" else 0.75,
            "rationale": f"Matched via {method}",
            "method": method,
        }
    return {
        "canonical_key": None,
        "confidence": 0.0,
        "rationale": "No match. Consider manual mapping.",
        "method": "UNMAPPED",
        "suggested_candidates": list(CANONICAL_KEYS)[:10],
    }


def suggest_batch(raw_labels: list[str]) -> list[dict[str, Any]]:
    """Batch suggestion for multiple raw labels."""
    return [suggest_canonical_key(r) for r in raw_labels]

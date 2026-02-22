"""
Deterministic routing: metric / line item -> candidate note_ids.

Use for repeatable behavior without LLM drift. LLM-assisted routing only when ambiguous.
"""
from __future__ import annotations

# metric_key or line_item keywords -> note numbers (as strings)
# Format: note_id = scope:number e.g. GROUP:21
ROUTING_TABLE: dict[str, list[str]] = {
    # Debt / borrowings
    "borrowings": ["GROUP:21"],
    "debt": ["GROUP:21"],
    "interest": ["GROUP:21"],
    "covenants": ["GROUP:21"],
    "maturity": ["GROUP:21"],
    "facility": ["GROUP:21"],
    "JIBAR": ["GROUP:21"],
    "unsecured": ["GROUP:21"],
    # Leases
    "lease": ["GROUP:20"],
    "ROU": ["GROUP:20"],
    "lease liability": ["GROUP:20"],
    "sale and leaseback": ["GROUP:20"],
    "lease maturity": ["GROUP:20"],
    # Risk / ECL / credit
    "credit risk": ["GROUP:43"],
    "ECL": ["GROUP:43"],
    "impairment": ["GROUP:43"],
    "risk management": ["GROUP:43"],
    "gearing": ["GROUP:43"],
    "capital risk": ["GROUP:43"],
    "financial instruments": ["GROUP:43"],
    # Contingencies
    "contingent": ["GROUP:22"],
    "contingencies": ["GROUP:22"],
    # Accounting policy
    "accounting policy": ["GROUP:1"],
    "policy for": ["GROUP:1"],
}


def route_to_notes(metric_key: str | None = None, line_item: str | None = None) -> list[str]:
    """
    Return candidate note_ids for the given metric or line item.
    Uses deterministic lookup; returns empty list if no match.
    """
    candidates: set[str] = set()
    search_terms = []
    if metric_key:
        search_terms.append(metric_key.lower())
    if line_item:
        for word in line_item.lower().split():
            if len(word) > 3:
                search_terms.append(word)

    for term in search_terms:
        for key, note_ids in ROUTING_TABLE.items():
            if key in term or term in key:
                candidates.update(note_ids)

    return list(candidates)

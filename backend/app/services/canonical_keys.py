"""
Canonical key gates for mapping.
Code accepts LLM mapping if: key in whitelist OR valid snake_case.
Semantic guardrails: expected_statement_for_key, expected_sign.
"""
from __future__ import annotations

import re

# Keys that must not be negative (impossible cases)
EXPECTED_POSITIVE_KEYS = frozenset({
    "total_assets", "total_equity", "shareholders_equity", "stated_capital",
    "cash", "revenue",  # revenue can be negative in rare cases; treat as WARN not FAIL
})

# Statement type each key belongs to (semantic guardrail: reject if key in wrong statement)
EXPECTED_STATEMENT_FOR_KEY: dict[str, str] = {
    # SFP
    "total_assets": "SFP", "non_current_assets": "SFP", "current_assets": "SFP",
    "total_equity": "SFP", "total_liabilities": "SFP", "non_controlling_interest": "SFP",
    "non_current_liabilities": "SFP", "current_liabilities": "SFP",
    # SCI
    "revenue": "SCI", "cost_of_sales": "SCI", "gross_profit": "SCI",
    "operating_profit": "SCI", "profit_before_tax": "SCI", "profit_for_the_year": "SCI",
    "income_tax_expense": "SCI", "finance_costs": "SCI",
    # CF
    "net_cash_from_operating": "CF", "net_cash_from_investing": "CF", "net_cash_from_financing": "CF",
}

# Keys that must NOT appear in a given statement (cross-statement guardrail).
# If key is in EXPECTED_STATEMENT_FOR_KEY and statement mismatches → reject.
# We do NOT use a strict whitelist (would reject valid mappings like property_plant_and_equipment).
# ALLOWED_KEYS_BY_STATEMENT: used only when we want to restrict; empty = allow valid snake_case.
ALLOWED_KEYS_BY_STATEMENT: dict[str, frozenset[str]] = {
    "SFP": frozenset(),   # empty = allow any valid snake_case in SFP
    "SCI": frozenset(),
    "IS": frozenset(),
    "CF": frozenset(),
    "SOCE": frozenset(),
    "SoCE": frozenset(),
}

# Known canonical keys used by reconciliation, financial engine, etc.
ALLOWED_CANONICAL_KEYS = frozenset({
    "total_assets", "non_current_assets", "current_assets",
    "total_equity", "equity", "shareholders_equity", "non_controlling_interest",
    "total_liabilities", "non_current_liabilities", "current_liabilities",
    "property_plant_equipment", "trade_receivables", "inventories", "cash",
    "short_term_borrowings", "current_portion_long_term_debt", "long_term_borrowings",
    "lease_liabilities_current", "lease_liabilities_non_current",
    "revenue", "cost_of_sales", "gross_profit", "operating_profit", "profit_before_tax",
    "profit_for_the_year", "total_comprehensive_income",
    "depreciation", "amortisation", "finance_costs", "income_tax_expense",
    "net_cash_from_operating", "net_cash_from_investing", "net_cash_from_financing",
})

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*(_[a-z0-9]+)*$")


def is_valid_canonical_key(key: str) -> bool:
    """True if key is UNMAPPED, in whitelist, or valid snake_case."""
    if not key or key == "UNMAPPED":
        return True
    if key in ALLOWED_CANONICAL_KEYS:
        return True
    return bool(_SNAKE_CASE_RE.match(key))


def apply_mapping_gate(mappings: list[dict], statement_type: str | None = None) -> list[dict]:
    """
    Gate: reject invalid keys, wrong-statement keys (semantic guardrail).
    If statement_type provided, reject keys that belong to a different statement.
    """
    out = []
    for m in mappings:
        m = dict(m)
        ck = m.get("canonical_key")
        stype = m.get("statement_type") or statement_type
        if not ck or ck == "UNMAPPED":
            out.append(m)
            continue
        if not is_valid_canonical_key(ck):
            m["canonical_key"] = "UNMAPPED"
            m["gate_rejected"] = "invalid_key"
        elif stype:
            st = "SoCE" if stype == "SOCE" else stype
            allowed = ALLOWED_KEYS_BY_STATEMENT.get(st)
            if allowed is not None and len(allowed) > 0 and ck not in allowed:
                m["canonical_key"] = "UNMAPPED"
                m["gate_rejected"] = f"key_not_allowed_in_{st}"
            elif ck in EXPECTED_STATEMENT_FOR_KEY:
                expected = EXPECTED_STATEMENT_FOR_KEY[ck]
                equivalent = {"SCI", "IS"} if expected == "SCI" else set()
                if expected != stype and stype not in equivalent:
                    m["canonical_key"] = "UNMAPPED"
                    m["gate_rejected"] = f"expected_statement_{expected}"
        out.append(m)
    return out

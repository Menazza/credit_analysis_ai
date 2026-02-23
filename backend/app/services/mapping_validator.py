"""
Validation checks before running engines.
Flag issues, downgrade confidence, but keep going.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def validate_facts(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Run balance checks. Returns {passed: bool, failures: list, warnings: list}.
    """
    by_period: dict[date, dict[str, float]] = {}
    for f in facts:
        pe = f["period_end"]
        if isinstance(pe, str):
            pe = date.fromisoformat(pe)
        if pe not in by_period:
            by_period[pe] = {}
        by_period[pe][f["canonical_key"]] = f["value_base"]

    failures = []
    warnings = []

    for period_end, vals in by_period.items():
        # IS: gross_profit ≈ revenue - cost_of_sales
        rev = vals.get("revenue")
        cos = vals.get("cost_of_sales")
        gp = vals.get("gross_profit")
        if rev is not None and cos is not None and gp is not None:
            expected = rev - abs(cos) if cos < 0 else rev - cos
            if abs(gp - expected) > 0.01 * max(abs(rev), 1):
                warnings.append({
                    "check": "gross_profit",
                    "period": str(period_end),
                    "expected": expected,
                    "actual": gp,
                })

        # BS: total_assets ≈ total_equity + total_liabilities
        ta = vals.get("total_assets")
        te = vals.get("total_equity")
        tl = vals.get("total_liabilities")
        if ta is not None and te is not None and tl is not None:
            expected = te + tl
            if abs(ta - expected) > 0.01 * max(abs(ta), 1):
                failures.append({
                    "check": "balance_sheet",
                    "period": str(period_end),
                    "expected": expected,
                    "actual": ta,
                })

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "warnings": warnings,
    }

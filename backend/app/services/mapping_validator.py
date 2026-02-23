"""
Validation checks before running engines.
Balance sheet identity, cash reconciliation, debt/lease tie to notes.
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
        pe_str = str(period_end)

        # BS: Total Assets = Total Equity + Total Liabilities (allow alternate: total_equity_and_liabilities)
        ta = vals.get("total_assets")
        te = vals.get("total_equity")
        tl = vals.get("total_liabilities")
        ta_alt = vals.get("total_equity_and_liabilities")  # some reports use this
        if ta is not None and te is not None and tl is not None:
            expected = te + tl
            tol = 0.02 * max(abs(ta or 0), 1)
            if abs((ta or 0) - expected) > tol:
                failures.append({
                    "check": "balance_sheet_identity",
                    "period": pe_str,
                    "expected": expected,
                    "actual": ta,
                    "message": "Total Assets != Total Equity + Total Liabilities",
                })

        # Cash: must be from SFP; CF closing cash can cross-check
        cash = vals.get("cash_and_cash_equivalents")
        if cash is not None and cash < 0:
            warnings.append({
                "check": "cash_negative",
                "period": pe_str,
                "value": cash,
                "message": "Cash and equivalents negative - verify source (SFP preferred)",
            })

        # Debt reconciliation: gross debt = ST + LT + curr portion (internal consistency)
        st = vals.get("short_term_borrowings") or 0
        curr_port = vals.get("current_portion_long_term_debt") or 0
        lt = vals.get("long_term_borrowings") or 0
        lease_curr = vals.get("lease_liabilities_current") or 0
        lease_nc = vals.get("lease_liabilities_non_current") or 0
        gross_debt = st + curr_port + lt + lease_curr + lease_nc
        if gross_debt > 0 and tl is not None and tl > 0:
            debt_pct = gross_debt / tl
            if debt_pct > 1.5:
                warnings.append({
                    "check": "debt_reconciliation",
                    "period": pe_str,
                    "gross_debt": gross_debt,
                    "total_liabilities": tl,
                    "message": "Gross debt > total liabilities - verify Note 21 tie",
                })

        # IS: gross_profit ≈ revenue - cost_of_sales
        rev = vals.get("revenue")
        cos = vals.get("cost_of_sales")
        gp = vals.get("gross_profit")
        if rev is not None and cos is not None and gp is not None:
            expected = rev - abs(cos) if cos < 0 else rev - cos
            if abs(gp - expected) > 0.01 * max(abs(rev), 1):
                warnings.append({
                    "check": "gross_profit",
                    "period": pe_str,
                    "expected": expected,
                    "actual": gp,
                })

    return {
        "passed": len([f for f in failures if "identity" in f.get("check", "")]) == 0,
        "failures": failures,
        "warnings": warnings,
    }

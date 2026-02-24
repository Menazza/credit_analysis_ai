"""
Validation checks before running engines.
Balance sheet identity, cash reconciliation, debt/lease tie to notes.
Track 3B: Conflict detection — duplicate canonical keys, sign anomalies, totals reconciliation.
"""
from __future__ import annotations

from datetime import date
from typing import Any

# Keys that must not be negative (revenue, equity, etc.)
POSITIVE_ONLY_KEYS = frozenset({
    "revenue", "gross_profit", "operating_profit", "profit_before_tax", "profit_after_tax",
    "total_assets", "total_equity", "total_liabilities", "cash_and_cash_equivalents",
    "total_current_assets", "total_current_liabilities",
})


def detect_mapping_conflicts(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Track 3B: Detect duplicates (same canonical_key + period + statement), sign anomalies,
    and totals reconciliation issues.
    """
    conflicts = []
    by_period: dict[date, dict[str, list[dict]]] = {}
    for f in facts:
        pe = f["period_end"]
        if isinstance(pe, str):
            pe = date.fromisoformat(pe)
        if pe not in by_period:
            by_period[pe] = {}
        key = f["canonical_key"]
        if key not in by_period[pe]:
            by_period[pe][key] = []
        by_period[pe][key].append(f)

    for pe, keys_dict in by_period.items():
        pe_str = str(pe)
        for key, flist in keys_dict.items():
            if len(flist) > 1:
                conflicts.append({
                    "type": "duplicate_canonical_key",
                    "period": pe_str,
                    "canonical_key": key,
                    "count": len(flist),
                    "values": [v.get("value_base") for v in flist[:5]],
                })
            if key in POSITIVE_ONLY_KEYS:
                for v in flist:
                    val = v.get("value_base")
                    if val is not None and val < 0:
                        conflicts.append({
                            "type": "sign_anomaly",
                            "period": pe_str,
                            "canonical_key": key,
                            "value": val,
                            "message": f"{key} expected positive, found {val}",
                        })

    # Totals reconciliation
    vals = {}
    for pe, kd in by_period.items():
        vals[pe] = {}
        for key, flist in kd.items():
            if flist:
                vals[pe][key] = flist[0].get("value_base")
    for pe, vmap in vals.items():
        pe_str = str(pe)
        rev = vmap.get("revenue")
        cos = vmap.get("cost_of_sales")
        gp = vmap.get("gross_profit")
        if rev is not None and cos is not None and gp is not None:
            expected_gp = rev - abs(cos) if cos < 0 else rev - cos
            if abs(gp - expected_gp) > 0.02 * max(abs(rev), 1):
                conflicts.append({
                    "type": "totals_reconciliation",
                    "period": pe_str,
                    "check": "gross_profit",
                    "expected": expected_gp,
                    "actual": gp,
                })
    return {"conflicts": conflicts, "passed": len(conflicts) == 0}


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

        # BS: Total Assets = Total Equity + Total Liabilities
        # Some reports use total_equity_and_liabilities (RHS) instead of total_assets
        ta = vals.get("total_assets") or vals.get("total_equity_and_liabilities")
        te = vals.get("total_equity")
        tl = vals.get("total_liabilities")
        if ta is not None and te is not None and tl is not None:
            expected = te + tl
            tol = 0.02 * max(abs(ta), 1)
            if abs(ta - expected) > tol:
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
        "passed": len(failures) == 0,
        "failures": failures,
        "warnings": warnings,
    }

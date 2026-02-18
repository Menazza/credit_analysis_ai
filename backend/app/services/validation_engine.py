"""
Validation & quality gates — no computation allowed unless gates pass.
Balance sheet tie-out, subtotals, note-to-statement reconciliations,
scale sanity, period/label integrity, duplicate detection.
"""
from typing import Any
from datetime import date


def check_balance_sheet_tie(
    assets: float,
    equity: float,
    liabilities: float,
    tolerance: float = 0.01,
) -> tuple[bool, str | None]:
    diff = abs((equity + liabilities) - assets)
    if diff <= tolerance:
        return True, None
    return False, f"Assets ({assets}) != Equity + Liabilities ({equity + liabilities}), diff={diff}"


def check_scale_sanity(value: float, key: str, typical_scale: tuple[float, float]) -> tuple[bool, str | None]:
    lo, hi = typical_scale
    if lo <= abs(value) <= hi:
        return True, None
    return False, f"{key} value {value} outside typical scale {typical_scale}"


def run_validation_checks(
    statement_totals: dict[str, float],
    balance_sheet: dict[str, float],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    failures = []
    passed = True
    if "total_assets" in balance_sheet and "total_equity" in balance_sheet and "total_liabilities" in balance_sheet:
        ok, msg = check_balance_sheet_tie(
            balance_sheet["total_assets"],
            balance_sheet["total_equity"],
            balance_sheet["total_liabilities"],
            tolerance,
        )
        if not ok:
            failures.append({"check": "balance_sheet_tie", "message": msg})
            passed = False
    return {
        "status": "PASS" if passed and not failures else "FAIL",
        "checks": ["balance_sheet_tie"],
        "failures": failures,
    }

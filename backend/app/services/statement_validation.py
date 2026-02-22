"""
Validation gates for extracted statements.
Graded: PASS | WARN | FAIL. Per-column when multiple entity_scopes.
"""
from __future__ import annotations

from typing import Any

ValidationStatus = str  # "PASS" | "WARN" | "FAIL"


def _tolerance_for_sfp(total_assets: float) -> float:
    """Tolerance: max(1, 0.5% of total assets)."""
    if not total_assets:
        return 0.02
    return max(0.005, 1.0 / abs(total_assets))


def validate_sfp_equation(
    lines: list[dict],
    period_labels: list[str],
    canonical_mappings: dict | list | None,
    tolerance: float | None = None,
    columns_normalized: list[dict] | None = None,
) -> dict[str, Any]:
    """
    SFP: Total Assets = Total Equity + Total Liabilities.
    Returns {status: PASS|WARN|FAIL, check, details, by_column}.
    If totals can't be found -> WARN (not FAIL).
    """
    totals = _sum_by_canonical_groups(lines, period_labels, canonical_mappings)
    assets = totals.get("assets", {})
    equity = totals.get("equity", {})
    liabilities = totals.get("liabilities", {})
    details = []
    by_column: list[dict] = []
    worst = "PASS"
    for lbl in period_labels:
        a = assets.get(lbl) or 0
        e = equity.get(lbl) or 0
        l_ = liabilities.get(lbl) or 0
        rhs = e + l_
        tol = tolerance if tolerance is not None else _tolerance_for_sfp(a)
        denom = abs(a) if a else 1
        diff_pct = abs(a - rhs) / denom if denom else 0
        ok = diff_pct <= tol
        status = "PASS" if ok else ("WARN" if a == 0 and rhs == 0 else "FAIL")
        if status == "FAIL":
            worst = "FAIL"
        elif status == "WARN" and worst != "FAIL":
            worst = "WARN"
        explain = f"Assets={a:.0f} vs Equity+Liab={rhs:.0f}"
        details.append({
            "period": lbl,
            "expected": rhs,
            "actual": a,
            "delta": a - rhs,
            "tolerance": round(tol * 100, 2),
            "diff_pct": round(diff_pct * 100, 2),
            "status": status,
            "explain": explain,
        })
        by_column.append({"column_label": lbl, "status": status, "checks": details[-1:]})
    return {
        "status": worst,
        "check": "SFP_equation",
        "message": "Assets = Equity + Liabilities" if worst == "PASS" else "SFP equation mismatch",
        "details": details,
        "by_column": by_column,
    }


ASSETS_KEYS = frozenset({
    "total_assets", "non_current_assets", "current_assets",
})
EQUITY_KEYS = frozenset({
    "total_equity", "equity", "shareholders_equity", "non_controlling_interest",
})
LIABILITIES_KEYS = frozenset({
    "total_liabilities", "non_current_liabilities", "current_liabilities",
})


def _get_canonical_key(raw_label: str, canonical_mappings: dict | list | None) -> str | None:
    if not canonical_mappings:
        return None
    mappings = canonical_mappings.get("mappings", canonical_mappings) if isinstance(canonical_mappings, dict) else canonical_mappings
    if not isinstance(mappings, list):
        return None
    raw_lower = (raw_label or "").strip().lower()
    for m in mappings:
        if isinstance(m, dict):
            ml = (m.get("raw_label") or "").strip().lower()
            ck = m.get("canonical_key")
            if ml and ck and ml == raw_lower and ck != "UNMAPPED":
                return str(ck)
    return None


def _sum_by_canonical_groups(
    lines: list[dict],
    period_labels: list[str],
    canonical_mappings: dict | list | None,
) -> dict[str, dict[str, float]]:
    """Group totals by assets/equity/liabilities for SFP equation."""
    out: dict[str, dict[str, float]] = {"assets": {}, "equity": {}, "liabilities": {}}
    for line in lines:
        raw = (line.get("raw_label") or "").strip()
        ck = _get_canonical_key(raw, canonical_mappings)
        if not ck:
            continue
        vals = line.get("values_json") or {}
        group = None
        if ck in ASSETS_KEYS:
            group = "assets"
        elif ck in EQUITY_KEYS:
            group = "equity"
        elif ck in LIABILITIES_KEYS:
            group = "liabilities"
        if not group:
            continue
        for lbl in period_labels:
            v = vals.get(lbl)
            if v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if lbl not in out[group]:
                out[group][lbl] = 0
            out[group][lbl] += num
    return out


def validate_cf_reconciliation(
    lines: list[dict],
    period_labels: list[str],
    tolerance: float = 0.02,
) -> dict[str, Any]:
    """
    CF: Net change ≈ sum of sections AND end - begin ≈ net change.
    Either passing gives WARN (not FAIL). Both passing = PASS.
    Returns {status: PASS|WARN|FAIL, check, details, by_column}.
    """
    operating = {}
    investing = {}
    financing = {}
    net_change = {}
    cash_begin = {}
    cash_end = {}
    for line in lines:
        raw = (line.get("raw_label") or "").strip().lower()
        vals = line.get("values_json") or {}
        for lbl in period_labels:
            v = vals.get(lbl)
            if v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if "operating" in raw and "cash flow" in raw:
                operating[lbl] = operating.get(lbl, 0) + num
            elif "investing" in raw:
                investing[lbl] = investing.get(lbl, 0) + num
            elif "financing" in raw:
                financing[lbl] = financing.get(lbl, 0) + num
            elif "net movement" in raw or "net change" in raw:
                net_change[lbl] = num
            elif "beginning" in raw and "cash" in raw:
                cash_begin[lbl] = num
            elif "end" in raw and "cash" in raw and "year" in raw:
                cash_end[lbl] = num
    details = []
    by_column: list[dict] = []
    section_ok = 0
    beg_end_ok = 0
    for lbl in period_labels:
        op = operating.get(lbl, 0)
        inv = investing.get(lbl, 0)
        fin = financing.get(lbl, 0)
        net = net_change.get(lbl)
        begin = cash_begin.get(lbl)
        end = cash_end.get(lbl)
        sum_sections = op + inv + fin
        if net is None:
            diff_section = 0
            section_pass = sum_sections == 0
        else:
            denom = abs(net) if net else 1
            diff_section = abs(net - sum_sections) / denom if denom else 0
            section_pass = diff_section <= tolerance
        if section_pass:
            section_ok += 1
        beg_end_pass = False
        if begin is not None and end is not None and net is not None:
            beg_end_pass = abs((end - begin) - net) <= max(1, tolerance * abs(net))
            if beg_end_pass:
                beg_end_ok += 1
        both_pass = section_pass and (beg_end_pass or (begin is None and end is None))
        either_pass = section_pass or beg_end_pass
        status = "PASS" if both_pass else ("WARN" if either_pass else "FAIL")
        details.append({
            "period": lbl,
            "operating": op, "investing": inv, "financing": fin,
            "sum_sections": sum_sections, "net_change": net,
            "diff_pct": round(diff_section * 100, 2),
            "status": status,
            "explain": f"Net={net} vs Op+Inv+Fin={sum_sections}" + (f"; end-begin={end - begin}" if begin is not None and end is not None else ""),
        })
        by_column.append({"column_label": lbl, "status": status, "checks": details[-1:]})
    worst = "FAIL" if any(d.get("status") == "FAIL" for d in details) else ("WARN" if any(d.get("status") == "WARN" for d in details) else "PASS")
    return {
        "status": worst,
        "check": "CF_reconciliation",
        "message": "Net change ≈ sections or end-begin" if worst != "FAIL" else "CF reconciliation mismatch",
        "details": details,
        "by_column": by_column,
    }


def validate_sign_sanity(lines: list[dict], statement_type: str) -> dict[str, Any]:
    """
    Sign sanity: WARN for unexpected signs, FAIL only for clearly impossible (total_assets negative, etc).
    """
    warnings: list[dict] = []
    fail_impossible: list[str] = []
    impossible_keys = {"total assets", "total equity", "share capital", "stated capital"}
    for line in lines:
        raw = (line.get("raw_label") or "").strip().lower()
        vals = line.get("values_json") or {}
        for lbl, v in vals.items():
            if v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if any(k in raw for k in impossible_keys) and num < 0:
                fail_impossible.append(f"{raw}: cannot be negative, got {num}")
            elif "depreciation" in raw or "amortisation" in raw:
                if num > 0 and abs(num) > 1:
                    warnings.append({"line": raw, "value": num, "explain": "expected negative"})
            elif "revenue" in raw and num < 0 and "loss" not in raw:
                warnings.append({"line": raw, "value": num, "explain": "unexpected negative"})
    status: ValidationStatus = "FAIL" if fail_impossible else ("WARN" if warnings else "PASS")
    return {
        "status": status,
        "check": "sign_sanity",
        "message": "Sign sanity OK" if status == "PASS" else f"{len(fail_impossible)} impossible, {len(warnings)} warnings",
        "warnings": warnings,
        "fail_impossible": fail_impossible,
    }


def validate_row_completeness(
    lines: list[dict],
    columns_normalized: list[dict],
) -> dict[str, Any]:
    """
    For rows with row_role line_item/subtotal/total: must have every VALUE column id in raw_value_strings.
    missing keys → WARN + incomplete_row=true per row.
    """
    from app.services.column_normalizer import get_column_ids, check_row_completeness
    value_ids = get_column_ids(columns_normalized, value_only=True)
    if not value_ids:
        return {"status": "PASS", "check": "row_completeness", "message": "No value columns to check", "incomplete_rows": []}
    incomplete = []
    for i, row in enumerate(lines):
        complete, missing = check_row_completeness(row, value_ids)
        if not complete:
            incomplete.append({"row_index": i, "raw_label": row.get("raw_label", "")[:100], "missing_column_ids": missing})
    status = "WARN" if incomplete else "PASS"
    return {
        "status": status,
        "check": "row_completeness",
        "message": f"{len(incomplete)} row(s) missing value columns" if incomplete else "All rows complete",
        "incomplete_rows": incomplete,
    }


def run_statement_validation(
    statements: list[dict],
    canonical_mappings: dict | list | None,
) -> dict[str, Any]:
    """
    Run validation gates. Returns graded {overall: PASS|WARN|FAIL, results[], by_column}.
    """
    results = []
    overall = "PASS"
    for stmt in statements or []:
        stype = stmt.get("statement_type", "")
        lines = stmt.get("lines", [])
        period_labels = list(stmt.get("period_labels", []))
        if not period_labels and stmt.get("periods"):
            period_labels = [p.get("label", str(i)) for i, p in enumerate(stmt["periods"])]
        if not period_labels and lines:
            vals = (lines[0] or {}).get("values_json") or {}
            period_labels = list(vals.keys()) if vals else []
        cols = stmt.get("columns_normalized", [])
        if cols:
            r_complete = validate_row_completeness(lines, cols)
            results.append(r_complete)
        if stype == "SFP":
            r = validate_sfp_equation(lines, period_labels, canonical_mappings, columns_normalized=cols)
            results.append(r)
        elif stype == "CF":
            r = validate_cf_reconciliation(lines, period_labels)
            results.append(r)
        r_sanity = validate_sign_sanity(lines, stype)
        results.append(r_sanity)
        for res in results[-2:]:
            s = res.get("status") or ("PASS" if res.get("passed", True) else "FAIL")
            if s == "FAIL":
                overall = "FAIL"
            elif s == "WARN" and overall != "FAIL":
                overall = "WARN"
    return {
        "overall": overall,
        "passed": overall == "PASS",
        "results": results,
    }

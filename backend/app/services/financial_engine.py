"""
Deterministic financial engine — no AI.
Computes ratios, cash flow, leverage, liquidity from normalized facts.
All outputs are versioned, reproducible, traceable.
"""
from datetime import date
from typing import Any
from decimal import Decimal


def get_fact(facts: dict[tuple[str, date], float], key: str, period_end: date) -> float | None:
    return facts.get((key, period_end))


def compute_ebitda(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    op = get_fact(facts, "operating_profit", period_end)
    da = get_fact(facts, "depreciation_amortisation", period_end)
    if op is None:
        return None
    return (op or 0) + (da or 0)


def compute_net_debt_ex_leases(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    cash = get_fact(facts, "cash_and_cash_equivalents", period_end)
    st_borr = get_fact(facts, "short_term_borrowings", period_end)
    curr_portion = get_fact(facts, "current_portion_long_term_debt", period_end)
    lt_borr = get_fact(facts, "long_term_borrowings", period_end)
    if cash is None and st_borr is None and curr_portion is None and lt_borr is None:
        return None
    debt = (st_borr or 0) + (curr_portion or 0) + (lt_borr or 0)
    return debt - (cash or 0)


def compute_net_debt_incl_leases(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    net_ex = compute_net_debt_ex_leases(facts, period_end)
    lease_curr = get_fact(facts, "lease_liabilities_current", period_end)
    lease_nc = get_fact(facts, "lease_liabilities_non_current", period_end)
    cash = get_fact(facts, "cash_and_cash_equivalents", period_end)
    if net_ex is None and lease_curr is None and lease_nc is None:
        return None
    leases = (lease_curr or 0) + (lease_nc or 0)
    return (net_ex or 0) + leases


def compute_interest_cover(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    ebit = get_fact(facts, "operating_profit", period_end)
    finance_costs = get_fact(facts, "finance_costs", period_end)
    if ebit is None or finance_costs is None or finance_costs >= 0:
        return None  # Net finance income: no meaningful interest cover
    return ebit / abs(finance_costs)


def compute_net_debt_to_ebitda(
    facts: dict[tuple[str, date], float], period_end: date
) -> float | None:
    net_debt = compute_net_debt_incl_leases(facts, period_end)
    ebitda = compute_ebitda(facts, period_end)
    if net_debt is None or ebitda is None or ebitda == 0:
        return None
    return net_debt / ebitda


def compute_ebitda_margin(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    ebitda = compute_ebitda(facts, period_end)
    revenue = get_fact(facts, "revenue", period_end)
    if ebitda is None or revenue is None or revenue <= 0:
        return None
    margin = 100.0 * (ebitda / revenue)
    if margin > 100.0 or margin < 0:
        return None  # Sanity check: impossible margin
    return margin


def compute_current_ratio(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    # Simplified: current assets / current liabilities from key line items
    cash = get_fact(facts, "cash_and_cash_equivalents", period_end) or 0
    receivables = get_fact(facts, "trade_receivables", period_end) or 0
    other_rcv = get_fact(facts, "other_receivables", period_end) or 0
    inventory = get_fact(facts, "inventories", period_end) or 0
    payables = get_fact(facts, "trade_payables", period_end) or 0
    st_borr = get_fact(facts, "short_term_borrowings", period_end) or 0
    curr_portion = get_fact(facts, "current_portion_long_term_debt", period_end) or 0
    curr_liab = payables + st_borr + curr_portion
    if curr_liab <= 0:
        return None
    curr_assets = cash + receivables + other_rcv + inventory
    cr = curr_assets / curr_liab
    if cr < 0:
        return None  # Sanity: negative current ratio
    return cr


def compute_fcf_conversion(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    net_cfo = get_fact(facts, "net_cfo", period_end)
    capex = get_fact(facts, "capex", period_end)
    ebitda = compute_ebitda(facts, period_end)
    if net_cfo is None or ebitda is None or ebitda == 0:
        return None
    fcf = (net_cfo or 0) - (capex or 0)
    return fcf / ebitda


def compute_dso(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    rec = get_fact(facts, "trade_receivables", period_end) or 0
    rev = get_fact(facts, "revenue", period_end)
    if not rev or rev <= 0:
        return None
    return (rec / rev) * 365


def compute_dio(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    inv = get_fact(facts, "inventories", period_end) or 0
    cos = get_fact(facts, "cost_of_sales", period_end)
    if cos is None or cos >= 0 or abs(cos) < 1:
        return None
    return (inv / abs(cos)) * 365


def compute_dpo(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    pay = get_fact(facts, "trade_payables", period_end) or 0
    cos = get_fact(facts, "cost_of_sales", period_end)
    if cos is None or cos >= 0 or abs(cos) < 1:
        return None
    return (pay / abs(cos)) * 365


def compute_wc_intensity(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    rec = get_fact(facts, "trade_receivables", period_end) or 0
    inv = get_fact(facts, "inventories", period_end) or 0
    pay = get_fact(facts, "trade_payables", period_end) or 0
    rev = get_fact(facts, "revenue", period_end)
    if not rev or rev <= 0:
        return None
    return (rec + inv - pay) / rev


# Provenance: formula inputs (canonical fact keys only; derived metrics use primitives)
_FORMULA_INPUTS: dict[str, list[str]] = {
    "ebitda": ["operating_profit", "depreciation_amortisation"],
    "net_debt_ex_leases": ["cash_and_cash_equivalents", "short_term_borrowings", "current_portion_long_term_debt", "long_term_borrowings"],
    "net_debt_incl_leases": ["cash_and_cash_equivalents", "short_term_borrowings", "current_portion_long_term_debt", "long_term_borrowings", "lease_liabilities_current", "lease_liabilities_non_current"],
    "interest_cover": ["operating_profit", "finance_costs"],
    "net_debt_to_ebitda": ["operating_profit", "depreciation_amortisation", "cash_and_cash_equivalents", "short_term_borrowings", "current_portion_long_term_debt", "long_term_borrowings", "lease_liabilities_current", "lease_liabilities_non_current"],
    "ebitda_margin": ["operating_profit", "depreciation_amortisation", "revenue"],
    "current_ratio": ["cash_and_cash_equivalents", "trade_receivables", "inventories", "trade_payables", "short_term_borrowings", "current_portion_long_term_debt"],
    "fcf_conversion": ["net_cfo", "capex", "operating_profit", "depreciation_amortisation"],
}


def _build_inputs(facts: dict[tuple[str, date], float], period_end: date, metric_key: str, value: float) -> dict:
    """Build inputs_used for provenance. Handles derived metrics (ebitda, net_debt_*)."""
    inputs = []
    keys = _FORMULA_INPUTS.get(metric_key, [])
    for k in keys:
        v = facts.get((k, period_end))
        if v is not None:
            inputs.append({"canonical_key": k, "period_end": period_end.isoformat(), "value": round(float(v), 2)})
    return {"formula_id": f"v1_{metric_key}", "inputs": inputs, "output": round(value, 4)}


def run_engine(facts: dict[tuple[str, date], float], periods: list[date], return_traces: bool = False) -> dict[str, Any] | tuple[dict, dict]:
    """Compute all metrics. Returns metric_key -> { period_end -> value }. If return_traces, returns (results, traces)."""
    results = {}
    traces: dict[str, dict[str, dict]] = {}
    for period_end in periods:
        ebitda = compute_ebitda(facts, period_end)
        if ebitda is not None:
            pe_s = period_end.isoformat()
            results.setdefault("ebitda", {})[pe_s] = ebitda
            if return_traces:
                traces.setdefault("ebitda", {})[pe_s] = _build_inputs(facts, period_end, "ebitda", ebitda)
        nd_ex = compute_net_debt_ex_leases(facts, period_end)
        if nd_ex is not None:
            pe_s = period_end.isoformat()
            results.setdefault("net_debt_ex_leases", {})[pe_s] = nd_ex
            if return_traces:
                traces.setdefault("net_debt_ex_leases", {})[pe_s] = _build_inputs(facts, period_end, "net_debt_ex_leases", nd_ex)
        nd_incl = compute_net_debt_incl_leases(facts, period_end)
        if nd_incl is not None:
            pe_s = period_end.isoformat()
            results.setdefault("net_debt_incl_leases", {})[pe_s] = nd_incl
            if return_traces:
                traces.setdefault("net_debt_incl_leases", {})[pe_s] = _build_inputs(facts, period_end, "net_debt_incl_leases", nd_incl)
        ic = compute_interest_cover(facts, period_end)
        if ic is not None:
            pe_s = period_end.isoformat()
            results.setdefault("interest_cover", {})[pe_s] = ic
            if return_traces:
                traces.setdefault("interest_cover", {})[pe_s] = _build_inputs(facts, period_end, "interest_cover", ic)
        nd_ebitda = compute_net_debt_to_ebitda(facts, period_end)
        if nd_ebitda is not None:
            pe_s = period_end.isoformat()
            results.setdefault("net_debt_to_ebitda", {})[pe_s] = nd_ebitda
            if return_traces:
                traces.setdefault("net_debt_to_ebitda", {})[pe_s] = _build_inputs(facts, period_end, "net_debt_to_ebitda", nd_ebitda)
        margin = compute_ebitda_margin(facts, period_end)
        if margin is not None:
            pe_s = period_end.isoformat()
            results.setdefault("ebitda_margin", {})[pe_s] = margin
            if return_traces:
                traces.setdefault("ebitda_margin", {})[pe_s] = _build_inputs(facts, period_end, "ebitda_margin", margin)
        cr = compute_current_ratio(facts, period_end)
        if cr is not None:
            pe_s = period_end.isoformat()
            results.setdefault("current_ratio", {})[pe_s] = cr
            if return_traces:
                traces.setdefault("current_ratio", {})[pe_s] = _build_inputs(facts, period_end, "current_ratio", cr)
        fcf_conv = compute_fcf_conversion(facts, period_end)
        if fcf_conv is not None:
            pe_s = period_end.isoformat()
            results.setdefault("fcf_conversion", {})[pe_s] = fcf_conv
            if return_traces:
                traces.setdefault("fcf_conversion", {})[pe_s] = _build_inputs(facts, period_end, "fcf_conversion", fcf_conv)
        dso = compute_dso(facts, period_end)
        if dso is not None:
            results.setdefault("dso_days", {})[period_end.isoformat()] = round(dso, 1)
        dio = compute_dio(facts, period_end)
        if dio is not None:
            results.setdefault("dio_days", {})[period_end.isoformat()] = round(dio, 1)
        dpo = compute_dpo(facts, period_end)
        if dpo is not None:
            results.setdefault("dpo_days", {})[period_end.isoformat()] = round(dpo, 1)
        wc_int = compute_wc_intensity(facts, period_end)
        if wc_int is not None:
            results.setdefault("wc_intensity", {})[period_end.isoformat()] = round(wc_int, 4)
    if return_traces:
        return results, traces
    return results

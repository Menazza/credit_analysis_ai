"""Trend Engine - growth, margin, WC, quality diagnostics."""
from __future__ import annotations
from datetime import date
from typing import Any
from app.services.financial_engine import get_fact, compute_ebitda, compute_net_debt_ex_leases, compute_net_debt_incl_leases

def _pct(c: float, p: float):
    return 100.0 * (c - p) / abs(p) if p and p != 0 else None

def run_trend_engine(facts, periods):
    ps = sorted(periods, reverse=True)
    if len(ps) < 2:
        return {"growth_diagnostics": {}, "balance_sheet_diagnostics": {}, "quality_diagnostics": {}}
    l, p = ps[0], ps[1]
    rc = get_fact(facts, "revenue", l) or 0
    rp = get_fact(facts, "revenue", p) or 0
    ec, ep = compute_ebitda(facts, l), compute_ebitda(facts, p)
    pac = get_fact(facts, "profit_after_tax", l)
    pap = get_fact(facts, "profit_after_tax", p)
    cfoc, cfop = get_fact(facts, "net_cfo", l), get_fact(facts, "net_cfo", p)
    cap = get_fact(facts, "capex", l)
    dac = get_fact(facts, "depreciation_amortisation", l)
    mc = 100.0 * (ec or 0) / rc if rc else None
    mp = 100.0 * (ep or 0) / rp if rp else None
    growth = {
        "revenue_growth_pct": _pct(rc, rp),
        "ebitda_growth_pct": _pct(ec or 0, ep or 0) if ec and ep else None,
        "pat_growth_pct": _pct(pac or 0, pap or 0) if pac is not None and pap is not None else None,
        "margin_delta_bps": (mc - mp) * 100 if mc and mp else None,
        "cfo_delta_pct": _pct(cfoc or 0, cfop or 0) if cfoc is not None and cfop is not None else None,
    }
    wck = ["trade_receivables", "inventories", "trade_payables", "other_receivables", "other_payables"]
    wcc = sum(get_fact(facts, k, l) or 0 for k in wck)
    wcp = sum(get_fact(facts, k, p) or 0 for k in wck)
    growth["working_capital_movement"] = wcc - wcp
    growth["working_capital_movement_pct"] = _pct(wcc, wcp) if wcp else None
    ndec = compute_net_debt_ex_leases(facts, l)
    ndep = compute_net_debt_ex_leases(facts, p)
    ndic = compute_net_debt_incl_leases(facts, l)
    ndip = compute_net_debt_incl_leases(facts, p)
    tac, tap = get_fact(facts, "total_assets", l), get_fact(facts, "total_assets", p)
    tec, tep = get_fact(facts, "total_equity", l), get_fact(facts, "total_equity", p)
    balance = {
        "net_debt_movement_ex_leases": (ndec or 0) - (ndep or 0),
        "net_debt_movement_incl_leases": (ndic or 0) - (ndip or 0),
        "asset_growth_pct": _pct(tac or 0, tap or 0) if tac and tap else None,
        "equity_movement": (tec or 0) - (tep or 0),
        "equity_growth_pct": _pct(tec or 0, tep or 0) if tec and tep else None,
    }
    cfo_eb = (cfoc / ec) if cfoc is not None and ec and ec != 0 else None
    epg = ((ec - pac) / ec * 100) if ec and pac is not None and ec != 0 else None
    cap_da = (abs(cap or 0) / abs(dac or 1)) if dac and dac != 0 else None
    quality = {
        "cfo_to_ebitda": round(cfo_eb, 4) if cfo_eb else None,
        "ebitda_to_pat_gap_pct": round(epg, 2) if epg else None,
        "capex_to_depreciation_ratio": round(cap_da, 2) if cap_da else None,
    }
    return {
        "growth_diagnostics": {k: v for k, v in growth.items() if v is not None},
        "balance_sheet_diagnostics": {k: v for k, v in balance.items() if v is not None},
        "quality_diagnostics": {k: v for k, v in quality.items() if v is not None},
        "periods_compared": [l.isoformat(), p.isoformat()],
    }

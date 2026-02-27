"""
Deterministic credit risk quantification (PD / LGD / EAD / Expected Loss).
LLM is not used for calculations; this module is fully rule-based and auditable.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _latest_period(facts_by_period: dict[date, dict[str, float]], metric_by_period: dict[date, dict[str, float]]) -> date | None:
    candidates = set(facts_by_period.keys()) | set(metric_by_period.keys())
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0]


def _nz(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


def _pd_decimal(pd_band: Any) -> float | None:
    """
    rating_engine config stores PD in percentage points (e.g. BBB=0.8 means 0.8%).
    Convert percentage points to decimal probability for EL math.
    """
    if pd_band is None:
        return None
    try:
        v = float(pd_band)
    except Exception:
        return None
    # 0.8 -> 0.008, 2.5 -> 0.025, 20 -> 0.20
    return max(0.0, min(1.0, v / 100.0))


def compute_credit_risk_quantification(
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
    rating_grade: str | None,
    pd_band: Any,
    analysis_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compute PD/LGD/EAD/EL and supporting assumptions.
    """
    pe = _latest_period(facts_by_period, metric_by_period)
    facts = facts_by_period.get(pe, {}) if pe else {}
    metrics = metric_by_period.get(pe, {}) if pe else {}

    # PD
    pd = _pd_decimal(pd_band)

    # EAD (drawn + CCF * undrawn)
    drawn = _nz(metrics.get("net_debt_incl_leases") or metrics.get("net_debt_ex_leases"))
    if drawn <= 0:
        drawn = max(
            0.0,
            _nz(facts.get("borrowings"))
            + _nz(facts.get("short_term_borrowings"))
            + _nz(facts.get("current_portion_long_term_debt"))
            + _nz(facts.get("lease_liabilities_current"))
            + _nz(facts.get("lease_liabilities_non_current")),
        )
    undrawn = _nz(metrics.get("undrawn_facilities"))
    ccf = 0.75
    ead = drawn + ccf * undrawn

    # Recovery / LGD (asset-bucket approach + stress haircut)
    cash = _nz(facts.get("cash_and_cash_equivalents"))
    inventory = _nz(facts.get("inventories"))
    receivables = _nz(facts.get("trade_and_other_receivables") or facts.get("trade_receivables"))
    ppe = _nz(facts.get("property_plant_and_equipment"))
    inv_prop = _nz(facts.get("investment_properties"))
    intangible = _nz(facts.get("intangible_assets"))

    # Recovery assumptions by asset class
    recovery_by_asset = {
        "cash": cash * 1.00,
        "investment_properties": inv_prop * 0.70,
        "inventory": inventory * 0.50,
        "receivables": receivables * 0.55,
        "ppe": ppe * 0.45,
        "intangibles": intangible * 0.05,
    }
    gross_recoverable = sum(recovery_by_asset.values())

    # Distress/legal/time haircut
    distress_haircut = 0.25
    net_recoverable = gross_recoverable * (1.0 - distress_haircut)

    # Seniority / enforceability adjustment
    cov = ((((analysis_output or {}).get("section_blocks") or {}).get("covenants") or {}).get("key_metrics") or {})
    covenant_breach = bool(cov.get("leverage_breach") or cov.get("interest_cover_breach"))
    seniority_factor = 0.85 if covenant_breach else 0.95
    net_recoverable *= seniority_factor

    recovery_rate = min(0.90, max(0.05, (net_recoverable / ead) if ead > 0 else 0.05))
    lgd = 1.0 - recovery_rate
    downturn_lgd = min(0.98, lgd * 1.25)

    expected_loss = (pd or 0.0) * lgd * ead
    expected_loss_downturn = (pd or 0.0) * downturn_lgd * ead

    # Lightweight stage allocation proxy (IFRS 9-like)
    stage = "Stage 2" if covenant_breach or _nz(metrics.get("net_debt_to_ebitda_incl_leases")) > 4.5 else "Stage 1"

    return {
        "period_end": pe.isoformat() if hasattr(pe, "isoformat") else str(pe) if pe else None,
        "rating_grade": rating_grade,
        "pd": pd,
        "pd_band_raw": pd_band,
        "lgd": lgd,
        "downturn_lgd": downturn_lgd,
        "ead": ead,
        "ccf": ccf,
        "drawn_exposure": drawn,
        "undrawn_commitments": undrawn,
        "expected_loss": expected_loss,
        "expected_loss_downturn": expected_loss_downturn,
        "ifrs9_stage": stage,
        "assumptions": {
            "distress_haircut": distress_haircut,
            "seniority_factor": seniority_factor,
            "recovery_by_asset": recovery_by_asset,
        },
    }

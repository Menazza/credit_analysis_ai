"""Unit tests for section-based credit analysis engines."""
from datetime import date
from app.services.business_risk_engine import run_business_risk_engine
from app.services.performance_engine import run_performance_engine
from app.services.liquidity_section_engine import run_liquidity_section_engine
from app.services.leverage_section_engine import run_leverage_section_engine
from app.services.notes_validation_engine import run_accounting_quality_engine
from app.services.stress_section_engine import run_stress_section_engine
from app.services.covenant_engine import run_covenant_engine
from app.services.rating_aggregation_engine import run_rating_aggregation
from app.services.section_orchestrator import run_section_based_analysis

def _make_facts() -> dict:
    pe1 = date(2025, 6, 30)
    pe2 = date(2024, 6, 30)
    return {
        ("revenue", pe1): 252701,
        ("revenue", pe2): 232088,
        ("operating_profit", pe1): 15380,
        ("operating_profit", pe2): 12828,
        ("depreciation_amortisation", pe1): 8012,
        ("depreciation_amortisation", pe2): 7000,
        ("profit_after_tax", pe1): 7583,
        ("profit_after_tax", pe2): 6221,
        ("net_cfo", pe1): 10984,
        ("net_cfo", pe2): 13841,
        ("capex", pe1): -6320,
        ("capex", pe2): -5718,
        ("cash_and_cash_equivalents", pe1): 9946,
        ("cash_and_cash_equivalents", pe2): 11732,
        ("trade_receivables", pe1): 5000,
        ("trade_payables", pe1): 30000,
        ("short_term_borrowings", pe1): 1000,
        ("current_portion_long_term_debt", pe1): 500,
        ("lease_liabilities_current", pe1): 2000,
        ("long_term_borrowings", pe1): 5000,
        ("lease_liabilities_non_current", pe1): 15000,
        ("total_equity", pe1): 30000,
        ("total_liabilities", pe1): 95000,
        ("finance_costs", pe1): -5100,
    }


def test_business_risk_engine():
    facts = _make_facts()
    periods = [date(2025, 6, 30), date(2024, 6, 30)]
    block = run_business_risk_engine(facts, periods)
    assert block["section_name"] == "Business Risk Assessment"
    assert "score" in block
    assert block["section_rating"] in ("Strong", "Adequate", "Weak")
    assert "key_metrics" in block


def test_performance_engine():
    facts = _make_facts()
    periods = [date(2025, 6, 30), date(2024, 6, 30)]
    block = run_performance_engine(facts, periods)
    assert block["section_name"] == "Financial Performance Analysis"
    assert "score" in block


def test_liquidity_section_engine():
    facts = _make_facts()
    periods = [date(2025, 6, 30)]
    block = run_liquidity_section_engine(facts, periods)
    assert block["section_name"] == "Cash Flow & Liquidity"
    assert block["key_metrics"].get("cash") == 9946


def test_leverage_section_engine():
    facts = _make_facts()
    periods = [date(2025, 6, 30)]
    block = run_leverage_section_engine(facts, periods)
    assert block["section_name"] == "Leverage & Capital Structure"


def test_accounting_quality_engine():
    facts_by_period = {"2025-06-30": {"revenue": 252701}}
    block = run_accounting_quality_engine({}, facts_by_period, 20000)
    assert block["section_name"] == "Accounting & Disclosure Quality"


def test_stress_section_engine():
    facts = _make_facts()
    periods = [date(2025, 6, 30)]
    block = run_stress_section_engine(facts, periods)
    assert block["section_name"] == "Stress Testing & Downside Analysis"
    assert "scenarios" in (block.get("key_metrics") or {})


def test_covenant_engine():
    block = run_covenant_engine({}, -0.52, 3.01, 11600)
    assert block["section_name"] == "Covenants & Headroom"
    assert block["key_metrics"].get("covenant_leverage_max") is not None


def test_rating_aggregation():
    blocks = {
        "business_risk": {"score": 70, "section_rating": "Strong"},
        "financial_performance": {"score": 65, "section_rating": "Adequate"},
        "liquidity": {"score": 75, "section_rating": "Strong"},
        "leverage": {"score": 85, "section_rating": "Strong"},
        "accounting_quality": {"score": 60, "section_rating": "Adequate"},
    }
    agg = run_rating_aggregation(blocks)
    assert "rating_grade" in agg
    assert "aggregate_score" in agg
    assert agg["aggregate_score"] > 50


def test_section_orchestrator():
    facts = _make_facts()
    periods = [date(2025, 6, 30), date(2024, 6, 30)]
    out = run_section_based_analysis(facts, periods, company_name="Test Co")
    assert "section_blocks" in out
    assert "aggregation" in out
    assert len(out["section_blocks"]) >= 7
    assert out["aggregation"]["rating_grade"]


def test_memo_composer_section_blocks():
    from app.services.memo_composer import build_sections_from_blocks

    out = run_section_based_analysis(_make_facts(), [date(2025, 6, 30), date(2024, 6, 30)], company_name="Test Co")
    section_texts = build_sections_from_blocks(
        company_name="Test Co",
        review_period_end=date(2025, 6, 30),
        rating_grade=out["aggregation"]["rating_grade"],
        recommendation="Maintain",
        section_blocks=out["section_blocks"],
        aggregation=out["aggregation"],
        facts_by_period={date(2025, 6, 30): {"revenue": 252701}},
        metric_by_period={},
    )
    assert "executive_summary" in section_texts
    assert "financial_performance" in section_texts
    assert "covenants_headroom" in section_texts
    assert "Test Co" in section_texts["executive_summary"]

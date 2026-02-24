"""
Mapping Pass A: Hard rules (exact matches + synonyms).
Highest precision. Sign conventions: expenses as negative where applicable.
"""
from __future__ import annotations

import re
# raw_label (normalized: lower, strip) -> (canonical_key, is_expense_negative)
# Expenses: cost_of_sales, operating_expenses, finance_costs, etc. stored as negative in our convention
RAW_TO_CANONICAL: list[tuple[list[str], str, bool]] = [
    # Income statement
    (["turnover", "revenue", "sales", "sale of merchandise", "sales of merchandise"], "revenue", False),
    (["cost of sales", "cost of goods sold", "cost of sales and services"], "cost_of_sales", True),
    (["gross profit"], "gross_profit", False),
    (["operating expenses", "administrative expenses", "distribution costs", "other operating expenses"], "operating_expenses", True),
    (["operating profit", "profit from operations", "profit before finance"], "operating_profit", False),
    (["depreciation", "depreciation and amortisation", "amortisation", "depreciation and amortization"], "depreciation_amortisation", True),
    (["finance income", "interest income", "interest revenue"], "finance_income", False),
    (["finance costs", "finance expenses", "interest expense", "net finance cost"], "finance_costs", True),
    (["share of profit of equity accounted investments", "share of profit of associates"], "share_of_profit_associates", False),
    (["profit before tax", "profit before income tax"], "profit_before_tax", False),
    (["income tax expense", "tax expense"], "income_tax_expense", True),
    (["profit for the year", "profit after tax", "profit for year", "net profit"], "profit_after_tax", False),
    # Balance sheet
    (["cash and cash equivalents", "cash and bank balances", "cash at bank and on hand"], "cash_and_cash_equivalents", False),
    (["trade receivables", "trade and other receivables", "amounts receivable"], "trade_receivables", False),
    (["other receivables", "other current assets"], "other_receivables", False),
    (["inventories", "inventory"], "inventories", False),
    (["total current assets"], "total_current_assets", False),
    (["property, plant and equipment", "property plant and equipment", "ppe"], "property_plant_equipment", False),
    (["right-of-use assets", "right of use assets", "lease assets"], "right_of_use_assets", False),
    (["intangible assets"], "intangible_assets", False),
    (["investment properties"], "investment_property", False),
    (["equity accounted investments", "investments in associates"], "investments_and_associates", False),
    (["total assets"], "total_assets", False),
    (["trade payables", "trade and other payables"], "trade_payables", False),
    (["other payables"], "other_payables", False),
    (["short-term borrowings", "short term borrowings", "bank overdraft"], "short_term_borrowings", False),
    (["current portion of long-term borrowings", "current portion long term debt"], "current_portion_long_term_debt", False),
    (["lease liabilities", "current lease liabilities"], "lease_liabilities_current", False),
    (["total current liabilities"], "total_current_liabilities", False),
    (["long-term borrowings", "long term borrowings", "non-current borrowings"], "long_term_borrowings", False),
    (["non-current lease liabilities"], "lease_liabilities_non_current", False),
    (["total liabilities"], "total_liabilities", False),
    (["total equity", "equity", "total equity attributable to owners", "equity attributable to owners of the parent"], "total_equity", False),
    (["total equity and liabilities"], "total_assets", False),  # RHS of BS = total assets
    # Cash flow
    (["cash generated from operations", "cash generated from operating activities"], "cash_generated_operations", False),
    (["cash flows from operating activities", "net cash from operating activities", "net cash flows from operating"], "net_cfo", False),
    (["purchase of property, plant and equipment", "capital expenditure", "additions to property plant", "investment in property, plant and equipment and other intangible assets to expand operations"], "capex", True),
    (["net cash flows from investing", "net cash used in investing"], "net_cfi", False),
    (["net cash flows from financing", "net cash used in financing"], "net_cff", False),
    (["net increase in cash", "net change in cash", "increase in cash"], "net_change_in_cash", False),
    (["interest paid"], "interest_paid", True),
    (["dividends paid", "dividends distributed"], "dividends_paid", True),
]


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").lower().strip())


def pass_a_match(raw_label: str) -> tuple[str | None, bool]:
    """
    Pass A: exact/synonym match.
    Returns (canonical_key, is_expense_negative) or (None, False) if no match.
    """
    normalized = _normalize_label(raw_label)
    for synonyms, canonical_key, is_expense in RAW_TO_CANONICAL:
        for syn in synonyms:
            if syn == normalized or normalized == syn:
                return canonical_key, is_expense
            if normalized.startswith(syn + " ") or normalized.endswith(" " + syn):
                return canonical_key, is_expense
    return None, False


def pass_b_patterns() -> list[tuple[str, str, bool]]:
    """
    Pass B: regex/keyword patterns.
    Returns list of (pattern, canonical_key, is_expense).
    """
    return [
        (r"depreciat", "depreciation_amortisation", True),
        (r"amorti[sz]ation", "depreciation_amortisation", True),
        (r"finance cost|interest expense", "finance_costs", True),
        (r"interest (income|revenue|received)", "finance_income", False),
        (r"cost of sales", "cost_of_sales", True),
        (r"gross profit", "gross_profit", False),
        (r"operating profit", "operating_profit", False),
        (r"profit before (tax|income tax)", "profit_before_tax", False),
        (r"profit (for|attributable to) (the year|period|owners)", "profit_after_tax", False),
        (r"total assets", "total_assets", False),
        (r"total equity", "total_equity", False),
        (r"total liabilities", "total_liabilities", False),
        (r"cash and cash", "cash_and_cash_equivalents", False),
        (r"trade receivables", "trade_receivables", False),
        (r"inventor", "inventories", False),
        (r"property.*plant|ppe", "property_plant_equipment", False),
        (r"right.of.use|lease assets", "right_of_use_assets", False),
        (r"intangible", "intangible_assets", False),
        (r"trade payables", "trade_payables", False),
        (r"short.term borrow|bank overdraft", "short_term_borrowings", False),
        (r"long.term borrow", "long_term_borrowings", False),
        (r"lease liabilit", "lease_liabilities_current", False),
        (r"cash generated|cash from operat", "cash_generated_operations", False),
        (r"capital expend|purchase of ppe", "capex", True),
        (r"interest paid", "interest_paid", True),
        (r"dividends paid", "dividends_paid", True),
        (r"net (increase|change|decrease) in cash", "net_change_in_cash", False),
        (r"revenue|turnover|sale of merchandise", "revenue", False),
    ]


def pass_b_match(raw_label: str) -> tuple[str | None, bool]:
    """
    Pass B: pattern match. Only used when Pass A fails.
    """
    normalized = _normalize_label(raw_label)
    for pattern, canonical_key, is_expense in pass_b_patterns():
        if re.search(pattern, normalized):
            return canonical_key, is_expense
    return None, False


def map_raw_label(raw_label: str) -> tuple[str | None, str, bool]:
    """
    Map raw_label to canonical_key using Pass A then Pass B.
    Returns (canonical_key, method, is_expense) or (None, "UNMAPPED", False).
    """
    key, is_exp = pass_a_match(raw_label)
    if key:
        return key, "RULE", is_exp
    key, is_exp = pass_b_match(raw_label)
    if key:
        return key, "REGEX", is_exp
    return None, "UNMAPPED", False

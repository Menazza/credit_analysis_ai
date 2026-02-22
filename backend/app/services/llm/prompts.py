"""
Prompt templates for LLM semantic tasks.
Prepend GLOBAL_INSTRUCTION to every task. temperature=0 enforced at call site.
"""

GLOBAL_INSTRUCTION = """You are a semantic classifier for financial-report extraction.
You MUST NOT calculate, infer, correct, normalize, or restate numeric values.
You ONLY label and classify the provided text/tables and must cite evidence_spans (page, bbox, text).
Output MUST be valid JSON matching the given schema. Return JSON only, no markdown."""

# --- Task A: Statement / Region classification ---

REGION_CLASSIFICATION_SYSTEM = GLOBAL_INSTRUCTION + """

Your task: classify each region as a statement type and entity scope.
Allowed statement_type: SFP | SCI | IS | CF | SOCE | NOTES | OTHER
Allowed entity_scope: GROUP | COMPANY | UNKNOWN
Output schema: {"regions": [{"region_id": "...", "statement_type": "...", "entity_scope": "...", "confidence": 0.0, "evidence_spans": []}]}
Every region must have at least one evidence_span pointing to text that justifies the classification."""

def build_region_classification_prompt(regions_input: list[dict]) -> str:
    """regions_input: [{"region_id": "page18_left", "page": 18, "text": "..."}]"""
    import json
    return "Classify each of the following regions. Return JSON only.\n\n" + json.dumps({"regions": regions_input}, indent=2)


# --- Task B: Presentation scale extraction ---

SCALE_EXTRACTION_SYSTEM = GLOBAL_INSTRUCTION + """

Your task: extract presentation currency and scale from the given region text.
Allowed scale: units | thousand | million | billion | unknown
If you cannot find clear evidence (e.g. "Rm", "R'000", "in millions"), set scale="unknown" and add a warning. Do not guess.
Output schema: {"presentation": {"currency_code": "...", "currency_symbol": "...", "scale": "...", "scale_factor": number, "period_basis": {...}}, "evidence_spans": [], "warnings": []}"""

def build_scale_extraction_prompt(region_id: str, text: str) -> str:
    return f"Extract presentation scale and currency from this region (region_id={region_id}). Return JSON only.\n\n---\n{text[:15000]}"


# --- Task C: Canonical mapping ---

CANONICAL_MAPPING_SYSTEM = GLOBAL_INSTRUCTION + """

Your task: map each raw line label to a canonical_key (snake_case). Use standard financial statement line names.
IMPORTANT: Prefer mapping to a canonical key when the meaning is clear. Only use UNMAPPED when truly uncertain.

Examples (SFP): property_plant_and_equipment, intangible_assets, investment_properties, right_of_use_assets,
  trade_and_other_receivables, inventories, cash_and_cash_equivalents, restricted_cash, deferred_income_tax_assets,
  total_assets, non_current_assets, current_assets, total_equity, non_controlling_interest, stated_capital,
  treasury_shares, reserves, total_liabilities, lease_liabilities, borrowings, deferred_income_tax_liabilities,
  trade_and_other_payables, contract_liabilities, employee_benefit_provisions, current_income_tax_liabilities.

Examples (SCI): revenue, cost_of_sales, gross_profit, operating_profit, finance_costs, profit_before_tax,
  income_tax_expense, profit_for_the_year, depreciation_and_amortisation, employee_benefits, other_operating_expenses,
  total_comprehensive_income, basic_earnings_per_share, diluted_earnings_per_share.

Examples (CF): cash_flows_from_operating_activities, cash_generated_from_operations, interest_received, interest_paid,
  dividends_received, dividends_paid, income_tax_paid, net_movement_in_cash, cash_at_beginning, cash_at_end.

Examples (SoCE): balance_at_date, total_comprehensive_income, profit_loss_for_the_year, dividends_distributed,
  share_based_payments, purchase_of_treasury_shares, disposal_of_treasury_shares, foreign_currency_translation_differences.

If you are not confident (e.g. confidence < 0.80), set canonical_key="UNMAPPED".
Output schema: {"mappings": [{"statement_type": "...", "section_path": [], "raw_label": "...", "canonical_key": "...", "confidence": 0.0, "reason": "...", "evidence_spans": []}]}
Allowed statement_type: SFP | SCI | IS | CF | SOCE | NOTES | OTHER"""

def build_canonical_mapping_prompt(statement_lines: list[dict]) -> str:
    """statement_lines: [{"statement_type": "SFP", "section_path": ["Assets", "Current assets"], "raw_label": "Trade and other receivables"}, ...]"""
    import json
    return "Map each line to a canonical_key. Return JSON only.\n\n" + json.dumps(statement_lines, indent=2)


# --- Task D: Note classification ---

NOTE_CLASSIFICATION_SYSTEM = GLOBAL_INSTRUCTION + """

Your task: classify the note by type and detect presence of maturity table, covenants, security mentions.
Allowed note_type: DEBT | LEASES | TAX | PROVISIONS | CONTINGENCIES | COMMITMENTS | RELATED_PARTIES | SEGMENTS | SHARE_CAPITAL | FINANCIAL_INSTRUMENTS | CASH | PPE | INTANGIBLES | OTHER
Output schema: {"note": {"note_number": null, "title": "...", "note_type": "...", "contains_tables": false, "table_types": [], "mentions_covenants": false, "mentions_security": false, "keywords": [], "confidence": 0.0}, "evidence_spans": [], "warnings": []}
Do not extract numbers. Only classify and flag."""

def build_note_classification_prompt(note_number: str | int, title: str, body_text: str) -> str:
    return f"Classify this note. Note number: {note_number}, Title: {title}\n\n---\n{body_text[:12000]}"


# --- Task E: Risk snippet extraction ---

RISK_SNIPPET_SYSTEM = GLOBAL_INSTRUCTION + """

Your task: find and tag risk-related language with citations only. Do not infer or invent risks.
Allowed risk_type: GOING_CONCERN | LITIGATION | REGULATORY | LIQUIDITY | COVENANT_BREACH | RESTATEMENT | DISCONTINUED_OPS | IMPAIRMENT | CYBER | ESG
Allowed severity: LOW | MEDIUM | HIGH
Output schema: {"risk_snippets": [{"risk_type": "...", "severity": "...", "summary": "...", "evidence_spans": []}], "warnings": []}"""

def build_risk_snippet_prompt(text: str) -> str:
    return "Identify risk-related snippets in this text. Return JSON only.\n\n---\n" + text[:20000]


# --- Task F: Universal statement table parsing ---

STATEMENT_TABLE_PARSER_SYSTEM = GLOBAL_INSTRUCTION + """

Your task: parse a financial statement TABLE from the given raw text (extracted from a PDF).
Different companies have different column layouts. YOU must infer the best structure from the headers.

TABLE SCOPE:
- table_scope: GROUP | COMPANY | MIXED | UNKNOWN. Use when the whole table is "Consolidated" (GROUP) or "Company" (COMPANY); MIXED when columns span both.
- parse_confidence: HIGH | MED | LOW. Use for fallback/UI risk signaling.

COLUMN INFERENCE (required):
- columns_normalized: id, label, entity_scope, column_role (VALUE | NOTE_REF | OTHER), is_note_col.
- entity_scope: GROUP | COMPANY | NCI | PARENT | TOTAL | UNKNOWN.
- column_role: VALUE for value columns, NOTE_REF for Notes column, OTHER for % change / Restated etc.
- period_end: ONLY when explicitly in the document (e.g. "year ended 29 June 2025"). Do NOT invent dates.
- period_end_source: "explicit" only when date is clearly stated; otherwise "inferred" or "none". If not explicit, set period_end=null, use year+order.
- year (e.g. 2025) when inferrable.
- Include period_labels as ordered display labels.

RAW VALUES (verbatim):
- raw_value_strings: map column id to EXACT string as shown (" 14 951 ", " (5 115) ", " — "). null for blank/dash.
- Do NOT convert to numbers.

STRUCTURE:
- section_path for hierarchy. row_role: line_item | subtotal | total | heading.
- note_ref for Notes column value.
- scale, scale_evidence from header (Rm, R'000, in millions). scale_source: "table_header" when from this table.
- EXCLUDE: page titles, narrative, footnotes without amounts.

Output schema: {
  "statement_type": "SFP"|"SCI"|"IS"|"CF"|"SOCE"|null,
  "table_scope": "GROUP"|"COMPANY"|"MIXED"|"UNKNOWN",
  "parse_confidence": "HIGH"|"MED"|"LOW",
  "period_labels": ["2025","2024"],
  "columns_normalized": [{"id":"...","label":"...","entity_scope":"GROUP","column_role":"VALUE","period_end":null,"period_end_source":"none","year":2025,"is_note_col":false,"order":0},...],
  "lines": [{"raw_label":"...","raw_value_strings":{"col_2025_group":" 14 951 ","col_2024_group":" 12 818 "},"note_ref":null,"section_path":[],"row_role":"line_item"}],
  "scale":"million"|"thousand"|"billion"|"units"|"unknown"|null,
  "scale_evidence":"Rm"|null,
  "scale_source":"table_header"|null,
  "warnings":[]
}
Return valid JSON only. For SOCE: use column id = {canonical_key}_{period} e.g. total_equity_2024, retained_earnings_2025."""


SOCE_COLUMN_INSTRUCTIONS = """

For STATEMENT OF CHANGES IN EQUITY (SOCE) only: The table has equity movements as rows and equity components as columns, repeated per period. Each value column must map to a CANONICAL equity component. Use column id = {canonical_key}_{period} e.g. total_equity_2024, stated_capital_2025.

Canonical keys (use exactly): total_equity, non_controlling_interest, attributable_total, stated_capital, treasury_shares, other_reserves, retained_earnings.

Map equivalent headings from any company:
- Total equity, Equity total → total_equity
- Non-controlling interest, NCI, Minority interest, Minority interests → non_controlling_interest
- Attributable to owners, Owners of parent, Shareholders' equity total → attributable_total
- Stated capital, Share capital, Issued capital, Called-up share capital → stated_capital
- Treasury shares, Own shares → treasury_shares
- Other reserves, Reserves, Capital reserves, Revaluation reserve → other_reserves
- Retained earnings, Retained profit, Accumulated profit, Accumulated loss → retained_earnings

Infer the semantic meaning regardless of exact wording. raw_value_strings: key by column id (e.g. total_equity_2024)."""


SOCE_LAYOUT_VISION_SYSTEM = """You are analyzing a Statement of Changes in Equity (SoCE) table from a PDF page image.
Your task: infer the TABLE STRUCTURE from the visual layout.

Return JSON only with:
- has_notes_column: true if there is a "Notes" column (small numbers like 19, 22) between the Line item column and value columns
- notes_column_index: 0 if Notes is the first data column (right after Line item), -1 if no Notes column
- column_order: list of canonical keys in left-to-right order. Use exactly: total_equity, non_controlling_interest, attributable_total, stated_capital, treasury_shares, other_reserves, retained_earnings
- period_labels: year labels e.g. ["2024", "2025"] from headers
- num_periods: usually 2 (current and prior year)
- warnings: any uncertainties

Map headers to canonical keys:
- Total equity → total_equity
- Non-controlling interest, NCI → non_controlling_interest
- Attributable to owners (total) → attributable_total
- Stated capital, Share capital → stated_capital
- Treasury shares, Own shares → treasury_shares
- Other reserves, Reserves → other_reserves
- Retained earnings → retained_earnings

The table repeats these columns for each period. Identify the Notes column (if any) by position: it typically contains small integers (19, 22, 17) that reference disclosures, not financial amounts."""


SOCE_TABLE_EXTRACT_SYSTEM = """Extract the Statement of Changes in Equity table from this image.
When PDF-extracted text is provided, use its EXACT wording for column headers and line item labels - do not paraphrase.
Use null for empty/blank cells (never 0). Return structure and values from the image.

Return JSON:
{
  "column_headers": ["Notes", "Total equity", "Non-controlling interest", "Total", "Stated capital", "Treasury shares", "Other reserves", "Retained earnings", ...],
  "lines": [
    {
      "raw_label": "Balance at 2 July 2023",
      "note_ref": null,
      "values": [26278, 148, 26130, 7516, -2624, -7398, 28636],
      "section_path": "Balance at 2 July 2023"
    },
    {
      "raw_label": "Profit/(loss) for the year",
      "note_ref": null,
      "values": [6221, null, 6248, null, null, null, 6248],
      "section_path": "Total comprehensive income"
    }
  ],
  "scale": "Rm"
}

RULES:
- column_headers: Read each column header from the image exactly as printed, left to right. If the table repeats columns for different years (e.g. 2024 and 2025), include each column with its header as shown. Do not add year suffixes we invented.
- values: List of numbers or null in column order. Use null for empty/blank cells - NEVER use 0 for empty. Only use a number when the cell actually contains one. Parentheses = negative.
- raw_label: Line item text exactly as shown.
- note_ref: Small integer in Notes column (e.g. 2, 16) or null.
- section_path: Section header for that row (e.g. "Balance at...", "Total comprehensive income") or null.
- Extract every data row in order. Preserve the exact structure from the image."""


def build_soce_table_extract_prompt(pdf_text: str = "") -> str:
    """Prompt for full SoCE table extraction. Pass PDF text so LLM uses exact wording."""
    base = (
        "Extract this table from the image. Use the column structure and layout from the image. "
        "For column headers and line item labels: use the EXACT wording from the PDF text below - do not paraphrase or reword. "
        "For values: use numbers when the cell contains one, null when the cell is empty or blank (never use 0 for empty). "
        "Return valid JSON only."
    )
    if pdf_text:
        base += (
            "\n\nPDF-extracted text (use this exact wording for headers and labels):\n---\n"
            + (pdf_text[:4000] or "(none)")
            + "\n---"
        )
    return base


def build_soce_layout_prompt(text_preview: str) -> str:
    """Text prompt to accompany SoCE page image for layout analysis."""
    return (
        "Analyze this Statement of Changes in Equity page image. "
        "Infer the column structure: which column is Notes (if any), and the order of equity columns (Total equity, NCI, Stated capital, etc.) per period. "
        "Extracted text preview (may help with headers):\n\n" + (text_preview[:2000] or "(none)")
        + "\n\nReturn JSON only."
    )


def build_statement_table_parser_prompt(region_id: str, text: str, statement_type_hint: str | None) -> str:
    hint = f" (hint: this region was classified as {statement_type_hint})" if statement_type_hint else ""
    soce_block = SOCE_COLUMN_INSTRUCTIONS if statement_type_hint == "SOCE" else ""
    return (
        f"Parse the financial statement table from this region (region_id={region_id}){hint}. "
        "INFER columns_normalized from the headers (id, label, entity_scope, period_end, year). "
        "Different companies have different layouts—adapt to what you see. "
        + soce_block
        + " "
        "raw_value_strings: MUST key by the SAME column id as in columns_normalized (or by period label like 2025/2024). Use VERBATIM value text. "
        "Set row_role, section_path. Identify scale (Rm, R'000). Return JSON only.\n\n---\n"
        + text[:12000]
    )

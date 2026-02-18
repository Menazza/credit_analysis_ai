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

Your task: map each raw line label to a canonical_key (snake_case). Use standard financial statement line names (e.g. trade_receivables, revenue, total_assets).
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
- Identify the COLUMN HEADERS (periods/years or column names, e.g. "2025", "2024", or "Total equity", "NCI" for Statement of Changes in Equity).
- For each DATA ROW: extract the line item label (e.g. "Property, plant and equipment") and the numeric value(s) for each column. Match values to columns by position or header.
- Include ONLY actual statement line items that have at least one numeric amount. EXCLUDE: page titles, section headings without amounts, narrative paragraphs, footnotes, "see note X" only lines, and any prose.
- If a row has a note number (e.g. "16" next to the label), set note_ref to that number.
- For Statement of Changes in Equity (multi-column layout), period_labels may be composite (e.g. "2025 Total equity", "2025 NCI", "2024 Total equity") and values_json must have one entry per such column.
- Output schema: {"statement_type": "SFP"|"SCI"|"IS"|"CF"|"SOCE"|null, "period_labels": ["2025", "2024"], "lines": [{"raw_label": "...", "values_json": {"2025": 123, "2024": 456}, "note_ref": "16"|null, "section_path": null|["Assets", "Current assets"]}], "warnings": []}
Return valid JSON only. Do not infer or correct numbers; use exactly what appears in the text."""


def build_statement_table_parser_prompt(region_id: str, text: str, statement_type_hint: str | None) -> str:
    hint = f" (hint: this region was classified as {statement_type_hint})" if statement_type_hint else ""
    return (
        f"Parse the financial statement table from this region (region_id={region_id}){hint}. "
        "Return JSON with period_labels and lines (raw_label + values_json per column). Return JSON only.\n\n---\n"
        + text[:12000]
    )

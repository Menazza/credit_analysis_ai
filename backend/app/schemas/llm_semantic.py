"""
Pydantic schemas for LLM semantic layer outputs.
Enforced on every LLM response; evidence_spans required for disputable claims.
"""
from typing import Literal

from pydantic import BaseModel, Field


# --- Evidence (required for all semantic claims) ---

class EvidenceSpan(BaseModel):
    """Standard citation: every semantic claim must reference evidence_spans."""
    document_version_id: str | None = Field(default=None, description="UUID of document version (injected when storing)")
    page: int = Field(ge=1, description="1-based page number")
    bbox: list[float] = Field(min_length=4, max_length=4, description="[x0, y0, x1, y1]")
    text: str = Field(default="", description="Cited text snippet")
    text_hash: str | None = Field(default=None, description="SHA256 of page text or span")
    region_id: str | None = Field(default=None, description="e.g. page18_left_statement")


# --- A) Statement / Region classification ---

StatementType = Literal["SFP", "SCI", "IS", "CF", "SOCE", "SoCE", "NOTES", "OTHER"]
EntityScope = Literal["GROUP", "COMPANY", "UNKNOWN"]


class RegionClassificationItem(BaseModel):
    region_id: str
    statement_type: StatementType
    entity_scope: EntityScope
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)


class StatementRegionClassification(BaseModel):
    """Output when classifying page/region as statement type."""
    regions: list[RegionClassificationItem] = Field(default_factory=list)


# --- B) Presentation scale & currency ---

ScaleLiteral = Literal["units", "thousand", "million", "billion", "unknown"]


class ComparativePeriod(BaseModel):
    year_end_date: str | None = None
    weeks: int | None = None
    restated: bool = False


class PeriodBasis(BaseModel):
    year_end_date: str | None = None
    weeks: int | None = None
    comparatives: list[ComparativePeriod] = Field(default_factory=list)


class PresentationScaleOutput(BaseModel):
    """Scale and currency per statement region. No guessing: missing evidence → unknown + warning."""
    presentation: dict = Field(
        description="Keys: currency_code, currency_symbol, scale, scale_factor, period_basis"
    )
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --- C) Canonical mapping (per line item) ---

class CanonicalMappingItem(BaseModel):
    statement_type: StatementType
    section_path: list[str] = Field(default_factory=list)
    raw_label: str
    canonical_key: str  # or "UNMAPPED" if confidence < threshold
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)


class CanonicalMappingOutput(BaseModel):
    """Mapping cache workhorse: raw_label → canonical_key with evidence."""
    mappings: list[CanonicalMappingItem] = Field(default_factory=list)


# --- D) Note classification ---

NoteTypeLiteral = Literal[
    "DEBT", "LEASES", "TAX", "PROVISIONS", "CONTINGENCIES", "COMMITMENTS",
    "RELATED_PARTIES", "SEGMENTS", "SHARE_CAPITAL", "FINANCIAL_INSTRUMENTS",
    "CASH", "PPE", "INTANGIBLES", "OTHER",
]


class NoteClassificationOutput(BaseModel):
    """Per-note: type, table types, covenant/security flags. No numeric extraction."""
    note: dict = Field(
        description="Keys: note_number, title, note_type, contains_tables, table_types, "
                    "mentions_covenants, mentions_security, keywords, confidence"
    )
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --- E) Risk snippet extraction (optional) ---

RiskTypeLiteral = Literal[
    "GOING_CONCERN", "LITIGATION", "REGULATORY", "LIQUIDITY", "COVENANT_BREACH",
    "RESTATEMENT", "DISCONTINUED_OPS", "IMPAIRMENT", "CYBER", "ESG",
]


class RiskSnippetItem(BaseModel):
    risk_type: RiskTypeLiteral
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    summary: str
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)


class RiskSnippetOutput(BaseModel):
    """Find and tag risk language with citations only."""
    risk_snippets: list[RiskSnippetItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --- F) Universal statement table parsing (headers + rows) ---

RowRoleLiteral = Literal["line_item", "subtotal", "total", "heading"]
ColumnEntityScope = Literal["GROUP", "COMPANY", "NCI", "PARENT", "TOTAL", "UNKNOWN"]
PeriodEndSource = Literal["explicit", "inferred", "none"]
ColumnRole = Literal["VALUE", "NOTE_REF", "OTHER"]
TableScope = Literal["GROUP", "COMPANY", "MIXED", "UNKNOWN"]
ParseConfidence = Literal["HIGH", "MED", "LOW"]


class ColumnNormalized(BaseModel):
    """Normalized column: LLM infers structure from headers (varies by company)."""
    id: str = Field(description="Unique column id, e.g. col_2025_group, col_2024_nci, notes")
    label: str = Field(description="Display label as shown (e.g. '2025', 'Total equity', 'Non-controlling interest')")
    entity_scope: ColumnEntityScope | None = Field(default=None, description="GROUP | COMPANY | NCI | PARENT | TOTAL | UNKNOWN")
    column_role: ColumnRole = Field(default="VALUE", description="VALUE | NOTE_REF | OTHER")
    period_end: str | None = Field(default=None, description="ISO date only when explicit in document")
    period_end_source: PeriodEndSource | None = Field(default=None, description="explicit | inferred | none. If not explicit, prefer period_end=null and use year+order.")
    year: int | None = Field(default=None, description="Year if inferrable (e.g. 2025)")
    parent_column_id: str | None = Field(default=None, description="Parent column id for sub-columns")
    is_note_col: bool = Field(default=False, description="True if Notes/reference column (backward compat)")
    order: int | None = Field(default=None, description="Column order (0-based)")


class StatementTableLine(BaseModel):
    """One row from a parsed statement table: label and raw value strings (verbatim)."""
    raw_label: str = Field(description="Line item label exactly as printed (e.g. 'Trade and other receivables')")
    raw_value_strings: dict[str, str | None] = Field(
        default_factory=dict,
        description="Map from column id (or period label) to VERBATIM value string. null for blank/dash.",
    )
    values_json: dict[str, float | None] | None = Field(
        default=None,
        description="Legacy: numeric values. Prefer raw_value_strings.",
    )
    note_ref: str | None = Field(default=None, description="Note number if present (e.g. '16')")
    section_path: list[str] | None = Field(default=None, description="Section hierarchy (e.g. ['Assets', 'Current assets'])")
    row_role: RowRoleLiteral = Field(default="line_item", description="line_item | subtotal | total | heading")


class StatementTableParseOutput(BaseModel):
    """Output when parsing a statement table: inferred column structure + data rows."""
    statement_type: StatementType | None = Field(default=None, description="Detected or hinted statement type")
    table_scope: TableScope | None = Field(default=None, description="GROUP | COMPANY | MIXED | UNKNOWN. Whole-table scope when columns are just years.")
    parse_confidence: ParseConfidence | None = Field(default=None, description="HIGH | MED | LOW. Use for fallback/UI risk.")
    period_labels: list[str] = Field(
        default_factory=list,
        description="Legacy: column labels in order. Use columns_normalized when present.",
    )
    columns_normalized: list[ColumnNormalized] = Field(
        default_factory=list,
        description="LLM-inferred column structure (id, label, entity_scope, period_end, year, is_note_col). Adapts to each company.",
    )
    lines: list[StatementTableLine] = Field(default_factory=list, description="Data rows: raw_value_strings keyed by column id")
    scale: ScaleLiteral | None = Field(default=None, description="Scale from table header: units | thousand | million | billion | unknown")
    scale_evidence: str | None = Field(default=None, description="Cited text for scale (e.g. 'Rm', 'R\\'000')")
    scale_confidence: float | None = Field(default=None, description="0-1 confidence in scale inference")
    scale_source: str | None = Field(default=None, description="table_header | doc_header | inferred")
    warnings: list[str] = Field(default_factory=list)


# --- G) SoCE layout from vision (image) ---

# --- H) SoCE full table extraction from page image ---

class SoCETableLine(BaseModel):
    """One row: label and values in column order. Use null for empty cells, not 0."""
    raw_label: str = Field(description="Line item label exactly as printed")
    note_ref: str | None = Field(default=None, description="Note number if present")
    values: list[float | None] = Field(
        default_factory=list,
        description="Values in column order. Use null for empty/blank cells - do NOT use 0 for empty.",
    )
    section_path: str | None = Field(default=None, description="Section header if any")


class SoCETableExtractOutput(BaseModel):
    """Table extracted verbatim from image. Use exactly as returned."""
    column_headers: list[str] = Field(
        default_factory=list,
        description="Column headers exactly as they appear in the image, left to right. Do not add or modify.",
    )
    lines: list[SoCETableLine] = Field(default_factory=list)
    scale: str | None = Field(default=None, description="Rm, R'000, etc. if visible")


class SoCELayoutOutput(BaseModel):
    """Output when analyzing SoCE table layout from page image. Guides parser on column structure."""
    has_notes_column: bool = Field(description="True if table has a Notes column between Line item and value columns")
    notes_column_index: int = Field(
        default=0,
        description="0-based index of Notes among data columns (0 = first col after line item is Notes). -1 if no Notes."
    )
    column_order: list[str] = Field(
        default_factory=list,
        description="Canonical equity column keys in document order: total_equity, non_controlling_interest, attributable_total, stated_capital, treasury_shares, other_reserves, retained_earnings",
    )
    period_labels: list[str] = Field(default_factory=list, description="Year labels e.g. [2024, 2025]")
    num_periods: int = Field(default=2, description="Number of period blocks (usually 2)")
    warnings: list[str] = Field(default_factory=list)


# Schema versions for cache keys (bump when schema or prompt changes)
SCHEMA_VERSION = "4"
PROMPT_VERSION = "6"  # SoCE layout vision + column instructions

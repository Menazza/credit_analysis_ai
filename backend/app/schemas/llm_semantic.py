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

StatementType = Literal["SFP", "SCI", "IS", "CF", "SOCE", "NOTES", "OTHER"]
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

class StatementTableLine(BaseModel):
    """One row from a parsed statement table: label and values per column."""
    raw_label: str = Field(description="Line item label as it appears (e.g. 'Trade and other receivables')")
    values_json: dict[str, float | None] = Field(
        default_factory=dict,
        description="Map from period/column label to numeric value or None if blank/dash (e.g. {\"2025\": 1234.5, \"2024\": null})",
    )
    note_ref: str | None = Field(default=None, description="Note number if present (e.g. '16')")
    section_path: list[str] | None = Field(default=None, description="Section hierarchy if applicable (e.g. ['Assets', 'Current assets'])")


class StatementTableParseOutput(BaseModel):
    """Output when parsing a statement table: column headers and data rows. Universal for SFP, SCI, CF, SOCE."""
    statement_type: StatementType | None = Field(default=None, description="Detected or hinted statement type")
    period_labels: list[str] = Field(
        default_factory=list,
        description="Column headers in order (e.g. ['2025', '2024'] or ['2025 Total equity', '2025 NCI', '2024 Total equity'])",
    )
    lines: list[StatementTableLine] = Field(default_factory=list, description="Data rows: label + values per column")
    warnings: list[str] = Field(default_factory=list)


# Schema versions for cache keys (bump when schema or prompt changes)
SCHEMA_VERSION = "1"
PROMPT_VERSION = "1"

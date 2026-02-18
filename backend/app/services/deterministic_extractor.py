"""
Deterministic AFS extractor (no LLM).

Goal:
- Take page-level text (from PDF or pre-built JSON).
- Detect key statements (SOFP, SOCI, CF) and basic meta.
- Parse simple multi-year tables into Statement / StatementLine rows.
- Store presentation scale in PresentationContext.

This is intentionally conservative and schema-compatible with the existing models
so we can iterate on rules without touching the DB layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentVersion
from app.models.extraction import PresentationContext, Statement, StatementLine


@dataclass
class PageText:
    page_no: int
    text: str


@dataclass
class SectionSpan:
    name: str
    page_start: int
    page_end: int
    anchors: List[str]
    confidence: float


@dataclass
class StatementExtract:
    section_name: str
    statement_type: str
    entity_scope: str
    years: List[str]
    items: Dict[str, Dict[str, float]]
    page_range: Tuple[int, int]


SECTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Group statements
    (re.compile(r"Consolidated statement of financial position", re.IGNORECASE), "SFP_GROUP"),
    (re.compile(r"Consolidated statement of (comprehensive income|profit and loss|income)", re.IGNORECASE), "SCI_GROUP"),
    (re.compile(r"Consolidated statement of cash flows?", re.IGNORECASE), "CF_GROUP"),
    # Company statements (not yet parsed, but detected for future use)
    (re.compile(r"Separate statement of financial position", re.IGNORECASE), "SFP_COMPANY"),
    (re.compile(r"Separate statement of comprehensive income", re.IGNORECASE), "SCI_COMPANY"),
]


NUM_RE = re.compile(r"[-+]?\d{1,3}(?:[ \u00A0]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")


def _normalise_text(t: str) -> str:
    t = t.replace("\u0007", " ")
    t = t.replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _detect_sections(pages: List[PageText]) -> List[SectionSpan]:
    """Detect statement sections based on simple heading regexes."""
    spans: List[SectionSpan] = []
    for p in pages:
        text = _normalise_text(p.text)
        for rx, name in SECTION_PATTERNS:
            if rx.search(text):
                spans.append(
                    SectionSpan(
                        name=name,
                        page_start=p.page_no,
                        page_end=p.page_no,  # simple: 1 page span; can be expanded later
                        anchors=[rx.pattern],
                        confidence=0.9,
                    )
                )
    # TODO: merge adjacent spans with same name and handle "continued" headings
    return spans


def _detect_currency_and_scale(pages: List[PageText]) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    """
    Heuristic currency / scale detection from the first couple of pages.

    Returns: (currency_code, scale_label, scale_factor)
    """
    head_text = "\n".join(_normalise_text(p.text) for p in pages[:3])
    currency = None

    if re.search(r"South Africa(n)? rand", head_text, re.IGNORECASE):
        currency = "ZAR"
    elif re.search(r"US(?:\s*Dollar|Dollars|\$)", head_text, re.IGNORECASE):
        currency = "USD"
    elif re.search(r"Euro", head_text, re.IGNORECASE):
        currency = "EUR"

    # Scale detection (Rm, R'000, R million, etc.)
    scale = None
    factor: Optional[float] = None
    if re.search(r"\bR(?:\s*)m\b|\bR million\b", head_text, re.IGNORECASE):
        scale, factor = "million", 1e6
    elif re.search(r"R'?000\b|\bthousand\b", head_text, re.IGNORECASE):
        scale, factor = "thousand", 1e3
    elif re.search(r"\bbillion\b", head_text, re.IGNORECASE):
        scale, factor = "billion", 1e9
    else:
        scale, factor = "units", 1.0

    return currency, scale, factor


def _detect_years_from_section_lines(lines: List[str]) -> Optional[List[str]]:
    """
    Detect reporting years from the first ~30 lines of a section.

    We don't rely on both years being on the same line (common OCR case),
    we just find all 20xx tokens and take the two largest.
    """
    years_found: List[int] = []
    for line in lines[:40]:
        for m in re.findall(r"\b(20\d{2})\b", line):
            try:
                y = int(m)
            except ValueError:
                continue
            if y not in years_found:
                years_found.append(y)
    if len(years_found) < 2:
        return None
    years_found.sort(reverse=True)
    y1, y2 = years_found[0], years_found[1]
    return [str(y1), str(y2)]


def _to_float(token: str, scale_factor: Optional[float]) -> Optional[float]:
    token = token.replace(" ", "").replace("\u00a0", "")
    # Handle parentheses as negatives: (123) => -123
    negative = False
    if token.startswith("(") and token.endswith(")"):
        negative = True
        token = token[1:-1]
    try:
        val = float(token)
    except ValueError:
        return None
    if negative:
        val = -val
    if scale_factor:
        val *= scale_factor
    return val


def _extract_label(line: str, last_two_tokens: Tuple[str, str]) -> str:
    n1, n2 = last_two_tokens
    # Greedy match from start up to the first of the last two numeric tokens
    pattern = rf"^(.*?){re.escape(n1)}.*{re.escape(n2)}.*$"
    m = re.match(pattern, line)
    if m:
        label = m.group(1)
    else:
        label = line
    label = label.strip(" :-\t")
    label = re.sub(r"\s+", " ", label)
    return label


def _normalise_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip()).lower()


def _parse_two_year_statement(
    section_name: str,
    statement_type: str,
    entity_scope: str,
    pages_map: Dict[int, PageText],
    span: SectionSpan,
    scale_factor: Optional[float],
) -> Optional[StatementExtract]:
    """Parse a simple two-year table (e.g. Shoprite SOFP / SOCI) into a StatementExtract."""
    texts: List[str] = []
    for page_no in range(span.page_start, span.page_end + 1):
        if page_no in pages_map:
            texts.append(_normalise_text(pages_map[page_no].text))
    if not texts:
        return None
    text = "\n".join(texts)
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]

    years = _detect_years_from_section_lines(lines)
    if not years:
        return None

    items: Dict[str, Dict[str, float]] = {}

    for line in lines:
        # Skip obvious headings
        if len(line) < 3 or "Notes" == line:
            continue
        nums = NUM_RE.findall(line)
        if len(nums) < 2:
            continue
        n1, n2 = nums[-2], nums[-1]
        v_current = _to_float(n1, scale_factor)
        v_prior = _to_float(n2, scale_factor)
        if v_current is None and v_prior is None:
            continue
        label = _extract_label(line, (n1, n2))
        if not label or len(label) < 3:
            continue
        key = _normalise_label(label)
        if not key:
            continue
        if key not in items:
            items[key] = {}
        # Assume column order: current year then prior year
        items[key][years[0]] = v_current
        items[key][years[1]] = v_prior

    if not items:
        return None

    return StatementExtract(
        section_name=section_name,
        statement_type=statement_type,
        entity_scope=entity_scope,
        years=years,
        items=items,
        page_range=(span.page_start, span.page_end),
    )


def _create_statement_rows(
    db: Session,
    version: DocumentVersion,
    se: StatementExtract,
) -> Statement:
    """Persist Statement and StatementLine rows from a StatementExtract."""
    stmt = Statement(
        document_version_id=version.id,
        statement_type=se.statement_type,
        entity_scope=se.entity_scope,
        periods_json=[{"label": y, "end_date": None} for y in se.years],
    )
    db.add(stmt)
    db.flush()

    line_no = 1
    for raw_label_norm, values in se.items.items():
        # Use original-ish label casing as raw_label (normalised key is fine for now)
        raw_label = raw_label_norm
        line = StatementLine(
            statement_id=stmt.id,
            line_no=line_no,
            raw_label=raw_label,
            section_path=None,
            note_refs_json=[],
            values_json=values,
            evidence_json={
                "pages": list(range(se.page_range[0], se.page_range[1] + 1)),
                "section_name": se.section_name,
            },
        )
        db.add(line)
        line_no += 1

    return stmt


def run_deterministic_extraction(
    db: Session,
    version: DocumentVersion,
    doc: Document,
    pages: List[dict],
) -> Dict[str, object]:
    """
    Main entry point used by Celery task:
    - Build PageText list
    - Detect meta (currency, scale)
    - Detect key statements
    - Parse basic two-year tables for group SOFP/SOCI/CF
    - Store PresentationContext + Statement/StatementLine rows
    """
    page_objs: List[PageText] = [PageText(page_no=p["page"], text=p.get("text", "") or "") for p in pages]
    pages_map: Dict[int, PageText] = {p.page_no: p for p in page_objs}

    # Meta: currency and scale
    currency, scale, scale_factor = _detect_currency_and_scale(page_objs)
    if currency or scale:
        pc = PresentationContext(
            document_version_id=version.id,
            scope="DOC",
            scope_key="presentation_scale",
            currency=currency,
            scale=scale,
            scale_factor=scale_factor,
            period_weeks=None,
            evidence_json={},
        )
        db.add(pc)

    sections = _detect_sections(page_objs)

    extracts: List[StatementExtract] = []
    for span in sections:
        if span.name == "SFP_GROUP":
            se = _parse_two_year_statement(
                section_name="Consolidated statement of financial position",
                statement_type="SFP",
                entity_scope="GROUP",
                pages_map=pages_map,
                span=span,
                scale_factor=scale_factor,
            )
            if se:
                extracts.append(se)
        elif span.name == "SCI_GROUP":
            se = _parse_two_year_statement(
                section_name="Consolidated statement of comprehensive income",
                statement_type="SCI",
                entity_scope="GROUP",
                pages_map=pages_map,
                span=span,
                scale_factor=scale_factor,
            )
            if se:
                extracts.append(se)
        elif span.name == "CF_GROUP":
            se = _parse_two_year_statement(
                section_name="Consolidated statement of cash flows",
                statement_type="CF",
                entity_scope="GROUP",
                pages_map=pages_map,
                span=span,
                scale_factor=scale_factor,
            )
            if se:
                extracts.append(se)

    created: Dict[str, object] = {"statements_created": 0, "sections_detected": [s.name for s in sections]}

    for se in extracts:
        _create_statement_rows(db, version, se)
        created["statements_created"] = int(created.get("statements_created", 0)) + 1

    return created


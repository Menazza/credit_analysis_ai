"""
Geometry-based extractor for SFP, SCI, and CF statements.
Same approach as soce_geometry_extractor but for simpler two-column statements.

These statements typically have:
- Label column (account names)
- Notes column (reference numbers)
- Current year column
- Prior year column

Pipeline:
1. Extract tokens with bboxes (PyMuPDF get_text("words"))
2. Detect table region (title + last line)
3. Build column bands from header year anchors
4. Classify tokens: label vs note vs amount
5. Build rows from y-clustering
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class Token:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int = 1

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class ColumnBand:
    key: str
    x_start: float
    x_end: float
    x_center: float
    is_notes: bool = False


def extract_tokens_from_page(pdf_bytes: bytes, page_no: int) -> list[Token]:
    """Extract tokens with bounding boxes."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    tokens: list[Token] = []
    try:
        page = doc[page_no - 1]
        words = page.get_text("words", sort=True)
        for w in words:
            x0, y0, x1, y1, text, *_ = w
            text = (text or "").strip()
            if not text:
                continue
            tokens.append(Token(text=text, x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1), page=page_no))
    finally:
        doc.close()
    return tokens


def detect_statement_type(tokens: list[Token]) -> tuple[str, str] | None:
    """
    Detect statement type and entity scope from page tokens.
    Returns (statement_type, entity_scope) or None.
    """
    header_text = " ".join(t.text.lower() for t in tokens[:100])
    
    entity_scope = "GROUP"
    if "separate" in header_text or "company" in header_text:
        entity_scope = "COMPANY"
    elif "consolidated" in header_text:
        entity_scope = "GROUP"
    
    if "statement of financial position" in header_text:
        return ("SFP", entity_scope)
    elif "statement of comprehensive income" in header_text or "statement of profit" in header_text:
        return ("SCI", entity_scope)
    elif "statement of cash flows" in header_text:
        return ("CF", entity_scope)
    elif "changes in equity" in header_text:
        return ("SOCE", entity_scope)
    
    return None


def find_statement_x_bounds(tokens: list[Token], statement_type: str) -> tuple[float, float] | None:
    """
    Find the x-coordinate bounds for a specific statement on a page.
    Handles two-column layouts where two statements appear side-by-side.
    
    Uses key content indicators rather than just titles:
    - SFP: "Total assets"
    - SCI: "Revenue" or "Gross profit"
    - CF: "Cash generated" or "Operating activities"
    - SOCE: "Balance at"
    
    Returns (x_min, x_max) for the statement region.
    """
    # Content indicators that appear only in specific statements
    content_indicators = {
        "SFP": ["total assets", "total equity and liabilities", "non-current assets", "current assets"],
        "SCI": ["gross profit", "revenue", "sale of merchandise", "operating profit"],
        "CF": ["cash generated", "operating activities", "investing activities", "net increase"],
        "SOCE": ["balance at", "total comprehensive income", "treasury shares"],
    }
    
    indicators = content_indicators.get(statement_type, [])
    if not indicators:
        return None
    
    # Find tokens that match content indicators
    indicator_tokens = []
    for t in tokens:
        text_lower = t.text.lower()
        for indicator in indicators:
            # Check if this token is part of the indicator phrase
            if any(word == text_lower for word in indicator.split()):
                indicator_tokens.append(t)
                break
    
    if not indicator_tokens:
        return None
    
    # Get the median x-center of indicator tokens (more robust than average)
    x_positions = sorted([t.x_center for t in indicator_tokens])
    median_x = x_positions[len(x_positions) // 2]
    
    # Determine page width
    page_width = max(t.x1 for t in tokens)
    page_mid = page_width / 2
    
    # If median is on left half, statement is on left; otherwise right
    if median_x < page_mid:
        return (0, page_mid - 20)
    else:
        return (page_mid - 20, page_width + 100)


def detect_table_region(tokens: list[Token], statement_type: str) -> tuple[float, float] | None:
    """Detect table top and bottom boundaries."""
    table_top: float | None = None
    table_bottom: float | None = None
    
    # Statement-specific keywords for table detection
    if statement_type == "SFP":
        title_keywords = ["assets", "non-current"]
        end_keywords = ["total equity and liabilities", "total assets", "director"]
    elif statement_type == "SCI":
        title_keywords = ["revenue", "sale", "merchandise"]
        end_keywords = ["total comprehensive income", "earnings per share", "director"]
    elif statement_type == "CF":
        title_keywords = ["operating", "cash", "generated", "activities"]
        end_keywords = ["cash and cash equivalents at end", "cash at end", "director"]
    else:
        title_keywords = ["statement"]
        end_keywords = ["total"]
    
    for t in tokens:
        lower = t.text.lower()
        # Find table top - look for content keywords, not title
        if any(kw == lower for kw in title_keywords):
            if table_top is None or t.y1 < table_top:
                table_top = t.y1
        # Find table bottom
        if any(kw in lower for kw in end_keywords):
            if table_bottom is None or t.y1 > table_bottom:
                table_bottom = t.y1
    
    if table_top is not None:
        return (table_top, table_bottom if table_bottom else 9999.0)
    return None


def detect_years(tokens: list[Token], table_top: float) -> list[str]:
    """Detect year columns from header area."""
    header_tokens = [t for t in tokens if table_top - 100 <= t.y0 <= table_top + 80]
    
    # First, find the "Notes" or "Rm" header to help identify the header row
    notes_y = None
    for t in header_tokens:
        if t.text.lower() in ("notes", "note", "rm"):
            notes_y = t.y0
            break
    
    years = []
    year_positions = []
    
    for t in header_tokens:
        text = t.text.strip()
        # Match 4-digit years (2020-2029), possibly with asterisk or other suffix
        match = re.match(r'^(20[2-9]\d)\*?$', text)
        if match:
            year = match.group(1)
            
            # Check if this year is in a column header row (near Notes/Rm header)
            # or in a title/description line (skip those)
            if notes_y is not None:
                # Year should be within 20 pixels of Notes header row
                if abs(t.y0 - notes_y) > 20:
                    continue
            else:
                # No Notes header found - check if year is surrounded by text
                # (indicating it's part of a sentence, not a column header)
                nearby_tokens = [
                    tok for tok in header_tokens 
                    if abs(tok.y0 - t.y0) < 3 and tok != t
                ]
                # If there are text tokens very close on both sides, skip
                left_tokens = [tok for tok in nearby_tokens if tok.x1 < t.x0 and t.x0 - tok.x1 < 10]
                right_tokens = [tok for tok in nearby_tokens if tok.x0 > t.x1 and tok.x0 - t.x1 < 10]
                if left_tokens and right_tokens:
                    # Surrounded by text - likely part of a title
                    continue
            
            if year not in years:
                years.append(year)
                year_positions.append((year, t.x_center, t.x0, t.x1))
    
    # Sort by x position (left to right, which is usually most recent first)
    year_positions.sort(key=lambda x: x[1])
    years = [y[0] for y in year_positions]
    
    return years, year_positions


def build_column_bands(tokens: list[Token], table_top: float, year_positions: list) -> list[ColumnBand]:
    """Build column bands from detected year positions."""
    if not year_positions:
        return []
    
    # Look for header tokens in a wider range above and below table_top
    # Column headers (Notes, years) may be significantly above the first data row
    header_tokens = [t for t in tokens if table_top - 60 <= t.y0 <= table_top + 80]
    
    bands: list[ColumnBand] = []
    
    # Find "Notes" column
    notes_x = None
    for t in header_tokens:
        if t.text.lower() == "notes" or t.text.lower() == "note":
            notes_x = t.x_center
            break
    
    # Label column starts at 0
    # First year column x0 (left edge) is the boundary for notes column
    first_year_x0 = year_positions[0][2] if year_positions else 300  # Use x0, not center
    first_col_x = year_positions[0][1] if year_positions else 300  # Center for column positioning
    
    if notes_x:
        label_end = notes_x - 10
        bands.append(ColumnBand(key="label", x_start=0, x_end=label_end, x_center=label_end / 2, is_notes=False))
        
        # Notes column ends close to the Notes header (note values align with header)
        # Use midpoint between notes_x and first_year_x0 to define where notes column ends
        # Note references are typically 1-2 digits, so they won't extend far beyond the header
        notes_end = min(notes_x + 30, first_year_x0 - 20)  # At most 30px after notes header center
        bands.append(ColumnBand(key="notes", x_start=label_end, x_end=notes_end, x_center=notes_x, is_notes=True))
    else:
        label_end = first_year_x0 - 30
        bands.append(ColumnBand(key="label", x_start=0, x_end=label_end, x_center=label_end / 2, is_notes=False))
    
    # Year columns - use actual token boundaries for more precision
    for i, (year, x_center, x0, x1) in enumerate(year_positions):
        if i == 0:
            x_start = bands[-1].x_end
        else:
            # Use midpoint between previous column right edge and this column left edge
            prev_x1 = year_positions[i - 1][3]  # Previous column right edge
            x_start = (prev_x1 + x0) / 2
        
        if i == len(year_positions) - 1:
            x_end = 9999.0
        else:
            # Use midpoint between this column right edge and next column left edge
            next_x0 = year_positions[i + 1][2]
            x_end = (x1 + next_x0) / 2
        
        bands.append(ColumnBand(key=year, x_start=x_start, x_end=x_end, x_center=x_center, is_notes=False))
    
    return bands


def _band_for_x(bands: list[ColumnBand], x: float) -> str | None:
    for b in bands:
        if b.x_start <= x <= b.x_end:
            return b.key
    return None


def _is_fully_in_notes_column(t: Token, bands: list[ColumnBand]) -> bool:
    """Check if token is fully within the Notes column (not just overlapping)."""
    notes_band = next((b for b in bands if b.is_notes), None)
    if not notes_band:
        return False
    # Token must be fully contained within the notes column
    # Use x_center to determine the primary column assignment
    return notes_band.x_start <= t.x_center <= notes_band.x_end


def classify_token(t: Token, bands: list[ColumnBand], years: list[str]) -> Literal["label", "note", "amount"] | None:
    """Classify token as label, note, or amount."""
    text = t.text.strip()
    
    # Notes: small integers (1-2 digits), optionally with decimal suffix (e.g., "38.1")
    # or letter suffix (e.g., "5a")
    if re.match(r'^\d{1,2}(\.\d{1,2})?[a-zA-Z]?$', text):
        if _is_fully_in_notes_column(t, bands):
            return "note"
    
    band = _band_for_x(bands, t.x_center)
    if not band:
        return None
    
    if band == "notes":
        if re.match(r'^\d{1,2}(\.\d{1,2})?[a-zA-Z]?$', text):
            return "note"
        return "label"
    
    if band == "label":
        return "label"
    
    # Year columns
    if band in years:
        # Check if it's a number
        if re.match(r'^\(?-?[\d\s,]+(?:\.\d+)?\)?$', text.replace("\u00a0", " ")):
            return "amount"
        if text.strip() in ("-", "—", "–"):
            return "amount"
        return "label"
    
    return "label"


def _parse_amount(text: str) -> float | None:
    """Parse numeric; (x) = negative. Handles space thousands."""
    s = text.strip().replace("\u00a0", " ")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace(" ", "").replace(",", "")
    if not s or not re.match(r'^[\d.-]+$', s):
        return None
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _combine_tokens_in_column(tokens: list[Token], x_gap_threshold: float = 15.0) -> str:
    """Combine adjacent tokens in a column (handles "26" + "278" -> "26 278")."""
    if not tokens:
        return ""
    sorted_tokens = sorted(tokens, key=lambda t: t.x0)
    parts = [sorted_tokens[0].text]
    for i in range(1, len(sorted_tokens)):
        prev = sorted_tokens[i - 1]
        curr = sorted_tokens[i]
        gap = curr.x0 - prev.x1
        if gap < x_gap_threshold:
            parts.append(curr.text)
        else:
            parts.append(" " + curr.text)
    return "".join(parts)


def build_rows(
    tokens: list[Token],
    bands: list[ColumnBand],
    years: list[str],
    table_top: float,
    table_bottom: float,
    statement_type: str,
    y_tolerance: float = 5.0,
) -> list[dict[str, Any]]:
    """Build rows from token y-clustering."""
    table_tokens = [t for t in tokens if table_top <= t.y_center <= table_bottom]
    amount_tokens = [t for t in table_tokens if classify_token(t, bands, years) == "amount"]
    note_tokens = [t for t in table_tokens if classify_token(t, bands, years) == "note"]
    label_tokens = [t for t in table_tokens if classify_token(t, bands, years) == "label"]
    
    if not amount_tokens:
        return []
    
    # Group amount tokens by y-position
    y_groups: dict[float, list[Token]] = {}
    for t in amount_tokens:
        y_key = round(t.y_center / y_tolerance) * y_tolerance
        if y_key not in y_groups:
            y_groups[y_key] = []
        y_groups[y_key].append(t)
    
    # Track label-only rows for multi-line labels
    label_y_groups: dict[float, list[Token]] = {}
    for t in label_tokens:
        y_key = round(t.y_center / y_tolerance) * y_tolerance
        if y_key not in y_groups:
            if y_key not in label_y_groups:
                label_y_groups[y_key] = []
            label_y_groups[y_key].append(t)
    
    all_ys = sorted(set(y_groups.keys()) | set(label_y_groups.keys()))
    
    rows: list[dict[str, Any]] = []
    current_section: str | None = None
    pending_labels: list[str] = []
    
    # Section detection patterns by statement type
    section_patterns = {
        "SFP": {
            "Assets": ["assets"],
            "Non-current assets": ["non-current assets"],
            "Current assets": ["current assets"],
            "Equity": ["equity"],
            "Liabilities": ["liabilities"],
            "Non-current liabilities": ["non-current liabilities"],
            "Current liabilities": ["current liabilities"],
        },
        "SCI": {
            "Revenue": ["revenue", "turnover"],
            "Operating expenses": ["operating expenses", "operating costs"],
            "Other comprehensive income": ["other comprehensive income"],
        },
        "CF": {
            "Operating activities": ["operating activities", "cash generated"],
            "Investing activities": ["investing activities"],
            "Financing activities": ["financing activities"],
        },
    }
    patterns = section_patterns.get(statement_type, {})
    
    for y_center in all_ys:
        has_amounts = y_center in y_groups
        row_amounts = y_groups.get(y_center, [])
        
        # Get labels for this row
        row_labels = [t for t in label_tokens
                      if abs(t.y_center - y_center) <= y_tolerance
                      and _band_for_x(bands, t.x_center) == "label"]
        row_labels.sort(key=lambda t: t.x0)
        row_label = " ".join(t.text for t in row_labels).strip()
        
        # Clean up label
        row_label = re.sub(r'^Rm\s+', '', row_label)
        
        # Check if this is a section header
        lower_label = row_label.lower()
        for section_name, keywords in patterns.items():
            if any(kw in lower_label for kw in keywords):
                current_section = section_name
                break
        
        if not has_amounts:
            if row_label:
                pending_labels.append(row_label)
            continue
        
        # Build full label
        if pending_labels:
            full_label = " ".join(pending_labels + ([row_label] if row_label else []))
            pending_labels = []
        else:
            full_label = row_label
        
        full_label = re.sub(r'^Rm\s+', '', full_label)
        
        # Get note reference
        note_val: str | None = None
        row_notes = [t for t in note_tokens
                     if abs(t.y_center - y_center) <= y_tolerance]
        if row_notes:
            note_val = row_notes[0].text.strip()
        
        # Group amounts by column and combine
        tokens_by_band: dict[str, list[Token]] = {}
        for t in row_amounts:
            band_key = _band_for_x(bands, t.x_center)
            if band_key and band_key in years:
                if band_key not in tokens_by_band:
                    tokens_by_band[band_key] = []
                tokens_by_band[band_key].append(t)
        
        # Parse values for each year
        values_by_year: dict[str, float | None] = {}
        for year in years:
            if year in tokens_by_band:
                combined_text = _combine_tokens_in_column(tokens_by_band[year])
                v = _parse_amount(combined_text)
                values_by_year[year] = v
            else:
                values_by_year[year] = None
        
        # Skip rows with no values
        if not any(v is not None for v in values_by_year.values()):
            continue
        
        rows.append({
            "raw_label": full_label or "",
            "note": note_val,
            "values_json": {"": values_by_year},
            "section": current_section,
            "period_labels": years,
        })
    
    return rows


def extract_statement_geometry(
    pdf_bytes: bytes,
    page_no: int,
    statement_type: str | None = None,
) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    """
    Full extraction pipeline for SFP, SCI, or CF statements.
    Handles two-column layouts by filtering tokens to the relevant page half.
    Returns (statement_type, entity_scope, period_labels, rows).
    """
    all_tokens = extract_tokens_from_page(pdf_bytes, page_no)
    if not all_tokens:
        return "", "", [], []
    
    # Use provided statement type or detect
    if statement_type:
        stmt_type = statement_type
        # Detect entity scope from tokens
        header_text = " ".join(t.text.lower() for t in all_tokens[:100])
        entity_scope = "COMPANY" if "separate" in header_text else "GROUP"
    else:
        detected = detect_statement_type(all_tokens)
        if not detected:
            return "", "", [], []
        stmt_type, entity_scope = detected
    
    # Find x-bounds for this statement (handles two-column layout)
    x_bounds = find_statement_x_bounds(all_tokens, stmt_type)
    if x_bounds:
        x_min, x_max = x_bounds
        # Filter tokens to only those within the statement's x-range
        tokens = [t for t in all_tokens if x_min <= t.x_center <= x_max]
    else:
        tokens = all_tokens
    
    if not tokens:
        return stmt_type, entity_scope, [], []
    
    # Detect table region
    region = detect_table_region(tokens, stmt_type)
    if not region:
        return stmt_type, entity_scope, [], []
    
    table_top, table_bottom = region
    
    # Detect years from the filtered tokens
    years, year_positions = detect_years(tokens, table_top)
    if not years:
        return stmt_type, entity_scope, [], []
    
    # Build column bands
    bands = build_column_bands(tokens, table_top, year_positions)
    if not bands:
        return stmt_type, entity_scope, [], []
    
    # Build rows
    rows = build_rows(tokens, bands, years, table_top, table_bottom, stmt_type)
    
    return stmt_type, entity_scope, years, rows


def extract_statement_structured_lines(
    pdf_bytes: bytes,
    page_no: int,
    statement_type: str | None = None,
    start_line_no: int = 1,
) -> list[dict[str, Any]]:
    """
    Drop-in replacement: returns same format as other extractors.
    """
    stmt_type, entity_scope, years, rows = extract_statement_geometry(pdf_bytes, page_no, statement_type)
    
    result: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        values_json = row.get("values_json", {})
        vals = values_json.get("") or {}
        
        result.append({
            "line_no": start_line_no + i,
            "raw_label": row.get("raw_label") or "",
            "note": row.get("note"),
            "values_json": {"": vals},
            "section": row.get("section"),
            "evidence_json": {"page": page_no},
            "period_labels": years,
            "statement_type": stmt_type,
            "entity_scope": entity_scope,
        })
    
    return result

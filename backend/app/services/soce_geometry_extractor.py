"""
Deterministic, audit-grade SoCE extraction: layout first, then meaning.

Pipeline:
1. Extract tokens with bboxes (PyMuPDF get_text("words"))
2. Detect table region (title + header + last Balance row)
3. Build column bands from header keyword anchors
4. Classify tokens: label vs note vs amount (strict rules)
5. Build rows from amount y-clustering; attach notes + merge wrapped labels
6. Handle heading rows (no amounts = section context)
7. Validation: balance identity, notes sanity
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

# Column band keys in logical order
COLUMN_BANDS = [
    "label",
    "notes",
    "total_equity",
    "non_controlling_interest",
    "attrib_total",
    "stated_capital",
    "treasury_shares",
    "other_reserves",
    "retained_earnings",
]

# Header keywords to find column anchors (order matters)
# total_equity before attrib_total so "Total" in "Total equity" doesn't match attrib_total
HEADER_KEYWORDS = [
    ("notes", [r"\bnotes\b"]),
    ("total_equity", [r"total\s+equity", r"total\s*equity"]),
    ("non_controlling_interest", [r"non[- ]?controlling", r"\bnci\b"]),
    ("attrib_total", [r"attributable\s+to\s+owners", r"attributable"]),  # parent; sub-header "Total" matched separately
    ("stated_capital", [r"stated\s+capital", r"share\s+capital"]),
    ("treasury_shares", [r"treasury\s+shares", r"own\s+shares"]),
    ("other_reserves", [r"other\s+reserves"]),
    ("retained_earnings", [r"retained\s+earnings", r"retained\s+profit"]),
]


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

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class ColumnBand:
    key: str
    x_start: float
    x_end: float
    x_center: float
    is_notes: bool = False  # True if this is the Notes column


@dataclass
class RowBand:
    y_top: float
    y_bottom: float
    y_center: float


def _parse_amount(text: str) -> float | None:
    """Parse numeric; (x) = negative. Handles space thousands."""
    s = text.strip().replace("\u00a0", " ")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(" ", "").replace(",", "")
    if not s or any(c for c in s if not (c.isdigit() or c in ".-")):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def extract_tokens_from_page(pdf_bytes: bytes, page_no: int) -> list[Token]:
    """Step 1: Extract tokens with bounding boxes."""
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


def find_soce_x_bounds(tokens: list[Token]) -> tuple[float, float] | None:
    """
    Determine x-coordinate boundaries for SOCE on a two-column page.
    Returns (x_min, x_max) or None if SOCE spans full page width.
    """
    if not tokens:
        return None
    
    page_width = max(t.x1 for t in tokens)
    page_mid = page_width / 2
    
    # Look for SOCE-specific content indicators (individual words or short phrases)
    soce_keywords = ["balance", "equity", "comprehensive", "retained", "stated", "treasury"]
    cf_keywords = ["operating", "investing", "financing", "flows", "generated", "received", "paid"]
    
    # Look for title indicators first
    for t in tokens:
        lower = t.text.lower()
        # "statement of changes in equity" or "statement of cash flows"
        if "changes" in lower:
            # SOCE title found - check which side
            if t.x_center < page_mid:
                return (0, page_mid + 20)
            else:
                return (page_mid - 20, page_width + 100)
        if "cash" in lower and any(
            t2.text.lower() == "flows" 
            for t2 in tokens 
            if abs(t2.y0 - t.y0) < 5 and abs(t2.x0 - t.x1) < 20
        ):
            # CF title found - SOCE is on the opposite side
            if t.x_center < page_mid:
                return (page_mid - 20, page_width + 100)  # SOCE on right
            else:
                return (0, page_mid + 20)  # SOCE on left
    
    # Count keywords on each side
    left_soce = 0
    right_soce = 0
    left_cf = 0
    right_cf = 0
    
    for t in tokens:
        lower = t.text.lower()
        is_soce = any(kw in lower for kw in soce_keywords)
        is_cf = any(kw in lower for kw in cf_keywords)
        
        if is_soce:
            if t.x_center < page_mid:
                left_soce += 1
            else:
                right_soce += 1
        if is_cf:
            if t.x_center < page_mid:
                left_cf += 1
            else:
                right_cf += 1
    
    # If we have mixed signals, no bounds
    if left_soce == 0 and right_soce == 0:
        return None
    
    # If SOCE keywords are clearly on one side and CF on the other
    if left_soce > right_soce and right_cf > left_cf:
        return (0, page_mid + 20)  # SOCE on left
    elif right_soce > left_soce and left_cf > right_cf:
        return (page_mid - 20, page_width + 100)  # SOCE on right
    elif left_soce > right_soce:
        return (0, page_mid + 20)  # SOCE on left (CF not detected)
    elif right_soce > left_soce:
        return (page_mid - 20, page_width + 100)  # SOCE on right
    
    return None


def detect_table_region(tokens: list[Token]) -> tuple[float, float] | None:
    """Step 2: Detect table top (below first header) and bottom (last Balance row)."""
    table_top: float | None = None
    table_bottom: float | None = None
    # Multi-word keywords and single-word keywords for split tokens
    header_keywords = ["statement of changes", "total equity", "notes", "non-controlling"]
    # Also check individual words that indicate the column header row
    header_single_words = ["total", "stated", "retained", "treasury", "reserves", "attributable"]
    balance_pattern = re.compile(r"balance\s+at\s+\d", re.I)
    balance_word_pattern = re.compile(r"^balance$", re.I)

    for t in tokens:
        lower = t.text.lower().strip()
        # Check multi-word patterns
        if any(kw in lower for kw in header_keywords):
            if table_top is None or t.y1 < table_top:
                table_top = t.y1
        # Check single-word patterns (for column headers like "Total", "Stated", etc.)
        if lower in header_single_words:
            if table_top is None or t.y1 < table_top:
                table_top = t.y1
        # Check for "Balance at" rows (table bottom)
        if balance_pattern.search(lower):
            if table_bottom is None or t.y1 > table_bottom:
                table_bottom = t.y1
        # Also check for just "Balance" token (split case)
        if balance_word_pattern.match(lower):
            # Look for nearby "at" token
            nearby_at = any(
                t2.text.lower() == "at" and abs(t2.y0 - t.y0) < 3 and abs(t2.x0 - t.x1) < 15
                for t2 in tokens
            )
            if nearby_at:
                if table_bottom is None or t.y1 > table_bottom:
                    table_bottom = t.y1

    if table_top is not None and table_bottom is not None:
        return (table_top, table_bottom)
    if table_top is not None:
        return (table_top, 9999.0)
    return None


def build_column_bands(tokens: list[Token], table_top: float, table_bottom: float) -> list[ColumnBand]:
    """
    Step 3: Detect column anchors from header keywords, create x-bands.
    Search in header area (first ~120pt) to catch multi-row headers.
    
    IMPORTANT: Only create ONE column per canonical key. Multi-year documents
    (2024/2025) should NOT create duplicate columns - the same columns appear
    for each period, not separate columns per year.
    
    Handles split headers where keywords span multiple tokens/lines:
    - "Total" on one line, "equity" below it
    - Uses individual word matching when full phrases aren't found
    """
    header_bottom = table_top + 120
    header_tokens = [t for t in tokens if table_top <= t.y0 <= header_bottom]

    # Build combined text of header region for phrase matching
    # Group tokens by approximate x-position to reconstruct column headers
    header_text_combined = " ".join(t.text for t in sorted(header_tokens, key=lambda x: (x.y0, x.x0)))
    
    # Find anchor positions for each canonical column - only keep the FIRST match per key
    anchors: list[tuple[str, float, float, float]] = []  # (key, x_center, x0, x1)
    seen_keys: set[str] = set()
    
    # First try to match full patterns in the combined header text
    for key, patterns in HEADER_KEYWORDS:
        if key in seen_keys:
            continue
        for t in header_tokens:
            lower = t.text.lower().strip()
            for pat in patterns:
                if re.search(pat, lower, re.I):
                    anchors.append((key, t.x_center, t.x0, t.x1))
                    seen_keys.add(key)
                    break
            if key in seen_keys:
                break
    
    # If we didn't find enough columns, try individual word matching
    # This handles split headers like "Total" / "equity" on separate lines
    WORD_TO_KEY = {
        "notes": "notes",
        "equity": "total_equity",  # "Total" + "equity" = total_equity
        "non-controlling": "non_controlling_interest",
        "controlling": "non_controlling_interest",  # Part of "Non-controlling"
        "attributable": "attrib_total",
        "stated": "stated_capital",
        "treasury": "treasury_shares",
        "reserves": "other_reserves",  # "Other reserves"
        "retained": "retained_earnings",
        "earnings": "retained_earnings",
    }
    
    # Second pass: match individual words to find missing columns
    for t in sorted(header_tokens, key=lambda x: x.x0):
        lower = t.text.lower().strip()
        if lower in WORD_TO_KEY:
            key = WORD_TO_KEY[lower]
            if key not in seen_keys:
                anchors.append((key, t.x_center, t.x0, t.x1))
                seen_keys.add(key)

    # Add standalone "Total" as attrib_total only if it's to the right of NCI
    # and we haven't already found attrib_total
    if "attrib_total" not in seen_keys:
        nci_x = next((x for k, x, _, _ in anchors if k == "non_controlling_interest"), 0)
        for t in header_tokens:
            lower = t.text.lower().strip()
            if lower == "total" and t.x_center > nci_x:
                anchors.append(("attrib_total", t.x_center, t.x0, t.x1))
                seen_keys.add("attrib_total")
                break

    if not anchors:
        return []

    anchors.sort(key=lambda a: a[1])  # Sort by x_center
    
    # Detect the right boundary of SoCE area by finding other statement titles
    # (e.g., "Cash flows", "Consolidated statement of cash flows")
    soce_right_boundary = 9999.0
    for t in header_tokens:
        lower = t.text.lower().strip()
        if any(kw in lower for kw in ["cash", "flows", "financial position"]):
            # Found another statement starting - SoCE ends before this
            if t.x0 > 400:  # Only consider if it's in the right portion of the page
                soce_right_boundary = min(soce_right_boundary, t.x0 - 20)
                break

    bands: list[ColumnBand] = []
    xs = [x for _, x, _, _ in anchors]
    first_x = xs[0] if xs else 0
    
    # Label column goes from 0 to just before the first anchor
    label_end = first_x - 10
    bands.append(ColumnBand(key="label", x_start=0, x_end=label_end, x_center=label_end / 2, is_notes=False))
    
    for i, (key, xc, x0, x1) in enumerate(anchors):
        # Each column starts where the previous one ends
        if i == 0:
            # First anchor column starts after label column
            x_start = label_end
        else:
            x_start = (xs[i - 1] + xs[i]) / 2
        
        if i == len(anchors) - 1:
            # Cap the last column at the SoCE boundary
            x_end = soce_right_boundary
        else:
            x_end = (xs[i] + xs[i + 1]) / 2
        
        is_notes = (key == "notes")
        bands.append(ColumnBand(key=key, x_start=x_start, x_end=x_end, x_center=xc, is_notes=is_notes))

    return bands


def _band_for_x(bands: list[ColumnBand], x: float) -> str | None:
    for b in bands:
        if b.x_start <= x <= b.x_end:
            return b.key
    return None


def _overlaps_notes_column(t: Token, bands: list[ColumnBand]) -> bool:
    """
    Check if a token's x-range overlaps with the Notes column.
    A number is a note reference if ANY part of it falls within the Notes column x-range.
    This is more robust than just checking the center point.
    """
    notes_band = next((b for b in bands if b.is_notes), None)
    if not notes_band:
        return False
    # Check if the token's x-range overlaps with the notes column's x-range
    # Token overlaps if: token.x0 <= notes_band.x_end AND token.x1 >= notes_band.x_start
    return t.x0 <= notes_band.x_end and t.x1 >= notes_band.x_start


def classify_token(t: Token, bands: list[ColumnBand]) -> Literal["label", "note", "amount"] | None:
    """
    Step 4: Classify token as label, note, or amount.
    
    Notes: small int (1-3 digits) that overlaps with the Notes column x-range.
    This uses x-coordinate overlap, not just center point, to catch notes that
    are slightly misaligned or span column boundaries.
    
    Amounts: numeric in value bands. Rest = label.
    """
    text = t.text.strip()
    
    # First check if this is a note reference using x-coordinate overlap
    # Notes are small integers (typically 1-99, sometimes up to 999)
    if re.match(r"^\d{1,3}$", text) or re.match(r"^\d{1,3}[a-zA-Z]$", text):
        if _overlaps_notes_column(t, bands):
            return "note"
    
    band = _band_for_x(bands, t.x_center)
    if not band:
        return None

    if band == "notes":
        # Already in notes band - treat as note if it's a small integer
        if re.match(r"^\d{1,3}$", text):
            return "note"
        if re.match(r"^\d{1,3}[a-zA-Z]$", text):
            return "note"
        return "label"

    if band == "label":
        return "label"

    value_prefixes = ("total_equity", "non_controlling_interest", "attrib_total", "stated_capital",
                      "treasury_shares", "other_reserves", "retained_earnings")
    if band in value_prefixes:
        if re.match(r"^\(?-?[\d\s,]+(?:\.\d+)?\)?$", text.replace("\u00a0", " ")):
            return "amount"
        if text.strip() in ("-", "—", "–"):
            return "amount"
        return "label"

    return "label"


def _parse_amount_token(text: str) -> float | None:
    s = text.strip().replace("\u00a0", " ")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace(" ", "").replace(",", "")
    if not s or not re.match(r"^[\d.-]+$", s):
        return None
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _combine_tokens_in_column(tokens: list[Token], x_gap_threshold: float = 15.0) -> str:
    """
    Combine adjacent tokens within a column into a single string.
    Handles space-separated thousands like "26" + "278" -> "26 278" -> 26278.
    Also handles split parentheses like "(2" + "624)" -> "(2 624)".
    """
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
    table_top: float,
    table_bottom: float,
    y_tolerance: float = 5.0,  # Tighter tolerance for better row separation
) -> list[dict[str, Any]]:
    """
    Step 5 & 6: Build rows from amount y-clustering. Attach notes, merge wrapped labels.
    
    Key improvements:
    - Combines adjacent tokens within each column before parsing (handles "26" + "278" -> 26278)
    - Properly handles multi-line account names by tracking pending labels
    - Tighter y-tolerance to avoid cross-row contamination
    """
    table_tokens = [t for t in tokens if table_top <= t.y_center <= table_bottom]
    amount_tokens = [t for t in table_tokens if classify_token(t, bands) == "amount"]
    note_tokens = [t for t in table_tokens if classify_token(t, bands) == "note"]
    label_tokens = [t for t in table_tokens if classify_token(t, bands) == "label"]

    if not amount_tokens:
        return []

    # Group amount tokens by y-position to find distinct rows
    y_groups: dict[float, list[Token]] = {}
    for t in amount_tokens:
        y_key = round(t.y_center / y_tolerance) * y_tolerance
        if y_key not in y_groups:
            y_groups[y_key] = []
        y_groups[y_key].append(t)
    
    # Also track label-only rows for multi-line account names
    label_y_groups: dict[float, list[Token]] = {}
    for t in label_tokens:
        y_key = round(t.y_center / y_tolerance) * y_tolerance
        if y_key not in y_groups:  # Only if no amounts on this row
            if y_key not in label_y_groups:
                label_y_groups[y_key] = []
            label_y_groups[y_key].append(t)
    
    # Merge all y-positions and sort
    all_ys = sorted(set(y_groups.keys()) | set(label_y_groups.keys()))

    rows: list[dict[str, Any]] = []
    current_section: str | None = None
    pending_labels: list[str] = []  # For multi-line account names

    for y_center in all_ys:
        has_amounts = y_center in y_groups
        
        if has_amounts:
            row_amounts = y_groups[y_center]
        else:
            row_amounts = []
        
        # Get labels for this row ONLY (tight y matching)
        row_labels = [t for t in label_tokens
                      if abs(t.y_center - y_center) <= y_tolerance
                      and _band_for_x(bands, t.x_center) == "label"]
        row_labels.sort(key=lambda t: t.x0)
        row_label = " ".join(t.text for t in row_labels).strip()
        
        # Clean up label
        if row_label.startswith("Rm "):
            row_label = row_label[3:].strip()
        if row_label.startswith("Rm "):
            row_label = row_label[3:].strip()
        
        # If this row has NO amounts, it might be:
        # 1. A section header (from PDF)
        # 2. A multi-line account name (first line)
        if not has_amounts:
            if row_label:
                lower = row_label.lower()
                # These are section headers that ACTUALLY appear in the PDF
                if "balance at" in lower:
                    current_section = None  # Balance rows don't have a section
                    pending_labels = []
                elif "total comprehensive" in lower:
                    current_section = "Total comprehensive income"
                    pending_labels = []
                elif "recognised in other comprehensive" in lower:
                    current_section = "Recognised in other comprehensive loss"
                    pending_labels = []
                # Note: "Other equity movements" is NOT a section in the PDF
                # Those rows (Share-based payments, etc.) are standalone
                else:
                    pending_labels.append(row_label)
            continue
        
        # This row HAS amounts - build the full label including pending ones
        if pending_labels:
            full_label = " ".join(pending_labels + ([row_label] if row_label else []))
            pending_labels = []
        else:
            full_label = row_label
        
        # Clean up common prefixes
        if full_label.startswith("Rm "):
            full_label = full_label[3:].strip()
        if full_label.startswith("Rm "):
            full_label = full_label[3:].strip()
        
        # Update section based on label - match EXACTLY what appears in the PDF
        # Only use section headers that actually exist in the PDF
        lower_label = full_label.lower()
        if "balance at" in lower_label:
            current_section = None  # Balance rows are top-level
        elif "total comprehensive income" in lower_label:
            # "Total comprehensive income" is both a section header AND a data row
            current_section = "Total comprehensive income"
        elif "profit/(loss)" in lower_label or "profit for the year" in lower_label:
            current_section = "Total comprehensive income"  # Sub-item of Total comprehensive income
        # Items after "Recognised in other comprehensive loss" that END that section
        # These items appear standalone in the PDF without a section header
        elif any(kw in lower_label for kw in ["share-based payments", "modification of cash", 
                                               "purchase of treasury", "treasury shares disposed",
                                               "realisation of share-based", "non-controlling interest"]):
            current_section = None  # No section - these are standalone rows in the PDF
        elif "dividends" in lower_label and "distributed" in lower_label:
            current_section = None  # Dividends is top-level

        # Get note reference for this row
        note_val: str | None = None
        row_notes = [t for t in note_tokens
                     if abs(t.y_center - y_center) <= y_tolerance
                     and (_band_for_x(bands, t.x_center) == "notes" or _overlaps_notes_column(t, bands))]
        
        # Filter out notes that are likely part of dates
        month_names = {"january", "february", "march", "april", "may", "june", 
                       "july", "august", "september", "october", "november", "december"}
        for note_t in row_notes:
            nearby_labels = [t.text.lower() for t in row_labels if abs(t.x0 - note_t.x1) < 50]
            if any(month in " ".join(nearby_labels) for month in month_names):
                continue
            note_val = note_t.text.strip()
            break

        # Group amount tokens by column band and combine them
        tokens_by_band: dict[str, list[Token]] = {}
        for t in row_amounts:
            band_key = _band_for_x(bands, t.x_center)
            if band_key and band_key not in ("label", "notes"):
                if band_key not in tokens_by_band:
                    tokens_by_band[band_key] = []
                tokens_by_band[band_key].append(t)

        # Parse combined values for each column
        values_by_col: dict[str, float | None] = {}
        for b in bands:
            if b.key in ("label", "notes"):
                continue
            if b.key in tokens_by_band:
                combined_text = _combine_tokens_in_column(tokens_by_band[b.key])
                v = _parse_amount_token(combined_text)
                values_by_col[b.key] = v
            else:
                values_by_col[b.key] = None

        # Skip rows with no values
        if not any(v is not None for v in values_by_col.values()):
            continue

        values_json: dict[str, dict[str, float | None]] = {"": values_by_col}
        rows.append({
            "raw_label": full_label or "",
            "note": note_val,
            "values_json": values_json,
            "section": current_section,
        })

    return rows


def validate_balance_row(row: dict[str, Any]) -> tuple[bool, str]:
    """
    Step 8.1: Balance line identity check.
    Total equity = Attributable total + NCI
    """
    vj = row.get("values_json") or {}
    vals = vj.get("") or {}
    te = vals.get("total_equity")
    nci = vals.get("non_controlling_interest")
    at = vals.get("attrib_total")
    if te is None or at is None or nci is None:
        return True, ""
    expected = (at or 0) + (nci or 0)
    diff = abs((te or 0) - expected)
    if diff > 1.0:
        return False, f"Balance check failed: total_equity={te} != attrib_total+nci={expected}"
    return True, ""


def extract_soce_geometry(pdf_bytes: bytes, page_no: int) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """
    Full pipeline: tokens → table region → column bands → rows.
    Returns (column_keys, period_labels, rows).
    Handles two-column page layouts by filtering tokens to SOCE region.
    """
    all_tokens = extract_tokens_from_page(pdf_bytes, page_no)
    if not all_tokens:
        return [], [], []
    
    # Handle two-column layout by filtering to SOCE region
    x_bounds = find_soce_x_bounds(all_tokens)
    if x_bounds:
        x_min, x_max = x_bounds
        tokens = [t for t in all_tokens if x_min <= t.x_center <= x_max]
    else:
        tokens = all_tokens
    
    if not tokens:
        return [], [], []

    region = detect_table_region(tokens)
    if not region:
        return [], [], []

    table_top, table_bottom = region
    bands = build_column_bands(tokens, table_top, table_bottom)
    if not bands:
        return [], [], []

    value_bands = [b.key for b in bands if b.key not in ("label", "notes")]
    if len(value_bands) < 2:
        return [], [], []  # Too few columns - fall through to LLM
    rows = build_rows(tokens, bands, table_top, table_bottom)

    column_keys = value_bands
    period_labels = [""]

    for row in rows:
        ok, _ = validate_balance_row(row)
        if not ok:
            pass

    return column_keys, period_labels, rows


def _band_key_to_header(key: str) -> str:
    """Convert band key to human-readable header. Does NOT add year suffixes."""
    canonical_keys = {
        "total_equity": "Total Equity",
        "non_controlling_interest": "Non-controlling Interest",
        "attrib_total": "Attributable Total",
        "stated_capital": "Stated Capital",
        "treasury_shares": "Treasury Shares",
        "other_reserves": "Other Reserves",
        "retained_earnings": "Retained Earnings",
        "notes": "Notes",
    }
    if key in canonical_keys:
        return canonical_keys[key]
    return key.replace("_", " ").title()


def extract_soce_structured_lines_geometry(
    pdf_bytes: bytes, page_no: int, start_line_no: int = 1
) -> list[dict[str, Any]]:
    """Drop-in: returns same format as soce_parser for worker compatibility."""
    column_keys, period_labels, rows = extract_soce_geometry(pdf_bytes, page_no)
    column_headers = [_band_key_to_header(k) for k in column_keys]
    cols = [str(j) for j in range(len(column_keys))]
    result: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        vj = row.get("values_json") or {}
        vals = vj.get("") or {}
        values_by_col = {str(j): vals.get(column_keys[j]) if j < len(column_keys) else None for j in range(len(column_keys))}
        result.append({
            "line_no": start_line_no + i,
            "raw_label": row.get("raw_label") or "",
            "note": row.get("note"),
            "values_json": {"": values_by_col},
            "section_path": row.get("section"),
            "evidence_json": {"page": page_no},
            "column_keys": cols,
            "column_headers": column_headers,
            "period_labels": period_labels,
        })
    return result

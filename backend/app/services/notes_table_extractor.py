"""
Extract and format tables within notes.
Uses coordinate-based extraction to preserve table structure as markdown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
import fitz


@dataclass
class TableColumn:
    name: str
    x_start: float
    x_end: float


@dataclass 
class ExtractedTable:
    title: str
    headers: list[str]
    rows: list[list[str]]
    
    def to_markdown(self) -> str:
        """Convert table to markdown format."""
        if not self.headers or not self.rows:
            return ""
        
        lines = []
        if self.title:
            lines.append(f"**{self.title}**\n")
        
        # Header row
        header_line = "| " + " | ".join(self.headers) + " |"
        lines.append(header_line)
        
        # Separator
        sep_line = "|" + "|".join(["---" for _ in self.headers]) + "|"
        lines.append(sep_line)
        
        # Data rows
        for row in self.rows:
            # Pad row to match header count
            while len(row) < len(self.headers):
                row.append("")
            row_line = "| " + " | ".join(row[:len(self.headers)]) + " |"
            lines.append(row_line)
        
        return "\n".join(lines)


def extract_tables_from_note_pages(
    doc: fitz.Document,
    start_page: int,
    end_page: int,
    note_title: str,
) -> list[ExtractedTable]:
    """
    Extract all tables from the given page range for a note.
    
    Returns list of ExtractedTable objects with proper structure.
    """
    tables: list[ExtractedTable] = []
    
    for page_idx in range(start_page - 1, min(end_page, len(doc))):
        page = doc[page_idx]
        page_tables = _extract_tables_from_page(page, note_title)
        tables.extend(page_tables)
    
    return tables


def _extract_tables_from_page(page: fitz.Page, note_title: str) -> list[ExtractedTable]:
    """Extract tables from a single page."""
    tables: list[ExtractedTable] = []
    
    words = page.get_text("words", sort=True)
    if not words:
        return tables
    
    # Group words by y-position
    lines: dict[int, list] = {}
    for w in words:
        x0, y0, x1, y1, text, *_ = w
        y_key = int(y0)
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append({
            "x0": x0, "x1": x1, "y0": y0, "y1": y1, 
            "text": text, "x_center": (x0 + x1) / 2
        })
    
    sorted_y = sorted(lines.keys())
    
    # Find table regions - look for "Rm" headers or year columns
    table_regions = _find_table_regions(lines, sorted_y)
    
    for region in table_regions:
        table = _extract_single_table(lines, sorted_y, region)
        if table and len(table.rows) > 0:
            tables.append(table)
    
    return tables


def _find_table_regions(
    lines: dict[int, list],
    sorted_y: list[int],
) -> list[dict]:
    """
    Find y-coordinate regions that contain tables.
    Returns list of {"start_y": int, "end_y": int, "header_y": int, "columns": [...]}
    """
    regions = []
    
    for i, y in enumerate(sorted_y):
        line_words = lines[y]
        line_text = " ".join(w["text"] for w in line_words).lower()
        
        # Detect table header line (contains "Rm" or year patterns)
        has_rm = any(w["text"].lower() == "rm" for w in line_words)
        has_year = any(re.match(r"^20\d{2}$", w["text"]) for w in line_words)
        has_total_header = "total" in line_text and any(
            w["text"].lower() in ["rm", "land", "buildings", "total"]
            for w in line_words
        )
        
        if has_rm or has_year or has_total_header:
            # Found a potential table header
            columns = _detect_columns_from_header(line_words, y, lines, sorted_y)
            
            if len(columns) >= 2:
                # Find table boundaries
                start_y = y
                end_y = _find_table_end(lines, sorted_y, i)
                
                regions.append({
                    "start_y": start_y,
                    "end_y": end_y,
                    "header_y": y,
                    "columns": columns,
                })
    
    return regions


def _detect_columns_from_header(
    header_words: list[dict],
    header_y: int,
    lines: dict[int, list],
    sorted_y: list[int],
) -> list[TableColumn]:
    """Detect column structure from header row."""
    columns = []
    
    # Sort by x position
    header_words_sorted = sorted(header_words, key=lambda w: w["x0"])
    
    # First column is usually the label column (leftmost, widest)
    if header_words_sorted:
        first_word = header_words_sorted[0]
        if first_word["x0"] < 100:
            # This is the label column - find its extent
            label_end = 200  # Default
            for w in header_words_sorted[1:]:
                if w["x0"] > 150:
                    label_end = w["x0"] - 10
                    break
            columns.append(TableColumn("Label", 0, label_end))
    
    # Remaining columns are value columns
    for w in header_words_sorted:
        if w["x0"] < 150:
            continue
        
        # Check if this is a column header
        text = w["text"]
        if text.lower() in ["rm", "total"] or re.match(r"^20\d{2}", text):
            # Use this word's position to define column
            col_name = text
            col_start = w["x0"] - 20
            col_end = w["x1"] + 20
            
            # Expand if there are words directly above/below in same x range
            columns.append(TableColumn(col_name, col_start, col_end))
    
    return columns


def _find_table_end(
    lines: dict[int, list],
    sorted_y: list[int],
    start_idx: int,
) -> int:
    """Find where the table ends (empty line or new section)."""
    consecutive_text_only = 0
    
    for i in range(start_idx + 1, len(sorted_y)):
        y = sorted_y[i]
        line_words = lines[y]
        
        # Check if line has numbers (indicating data row)
        has_numbers = any(
            re.match(r"^[\d\s\(\)—–-]+$", w["text"].replace(",", "").replace(".", ""))
            for w in line_words
            if w["x0"] > 150  # Only check value columns
        )
        
        if not has_numbers:
            consecutive_text_only += 1
            if consecutive_text_only >= 3:
                return sorted_y[i - 2] if i >= 2 else y
        else:
            consecutive_text_only = 0
        
        # Stop at page footer indicators
        line_text = " ".join(w["text"] for w in line_words).lower()
        if "shoprite holdings" in line_text or "annual financial" in line_text:
            return sorted_y[i - 1] if i > 0 else y
    
    return sorted_y[-1] if sorted_y else 0


def _extract_single_table(
    lines: dict[int, list],
    sorted_y: list[int],
    region: dict,
) -> ExtractedTable | None:
    """Extract a single table from the region."""
    columns = region["columns"]
    if len(columns) < 2:
        return None
    
    headers = [col.name for col in columns]
    rows = []
    
    # Find y indices in range
    start_y = region["start_y"]
    end_y = region["end_y"]
    
    for y in sorted_y:
        if y <= start_y:
            continue
        if y > end_y:
            break
        
        line_words = lines[y]
        row = _assign_words_to_columns(line_words, columns)
        
        # Only add rows that have at least one non-empty cell
        if any(cell.strip() for cell in row):
            rows.append(row)
    
    return ExtractedTable(
        title="",
        headers=headers,
        rows=rows,
    )


def _assign_words_to_columns(
    words: list[dict],
    columns: list[TableColumn],
) -> list[str]:
    """Assign words to columns based on x-coordinate."""
    row = ["" for _ in columns]
    
    for word in words:
        x_center = word["x_center"]
        text = word["text"]
        
        # Find which column this word belongs to
        for i, col in enumerate(columns):
            if col.x_start <= x_center <= col.x_end:
                if row[i]:
                    row[i] += " " + text
                else:
                    row[i] = text
                break
        else:
            # Word doesn't fit any column - try to find closest
            min_dist = float("inf")
            closest_col = 0
            for i, col in enumerate(columns):
                dist = min(abs(x_center - col.x_start), abs(x_center - col.x_end))
                if dist < min_dist:
                    min_dist = dist
                    closest_col = i
            
            if min_dist < 50:
                if row[closest_col]:
                    row[closest_col] += " " + text
                else:
                    row[closest_col] = text
    
    return row


def format_note_with_tables(
    doc: fitz.Document,
    note_id: str,
    title: str,
    start_page: int,
    end_page: int,
) -> str:
    """
    Extract note content with tables formatted as markdown.
    
    Returns formatted text combining narrative and tables.
    """
    parts = []
    parts.append(f"# Note {note_id}: {title}\n")
    parts.append(f"*Pages {start_page}-{end_page}*\n")
    
    # Extract tables
    tables = extract_tables_from_note_pages(doc, start_page, end_page + 1, title)
    
    # Get raw text for narrative sections
    for page_idx in range(start_page - 1, min(end_page, len(doc))):
        page = doc[page_idx]
        text = page.get_text()
        
        # Find note section in text
        note_pattern = rf"(?:^|\n){note_id}\n{re.escape(title[:15])}"
        match = re.search(note_pattern, text, re.IGNORECASE)
        
        if match:
            # Extract narrative portions (text before/between tables)
            narrative = _extract_narrative(text[match.start():], tables)
            parts.append(narrative)
        elif page_idx == start_page - 1:
            # First page but couldn't find header - use raw text
            parts.append(text[:2000])
    
    # Add formatted tables
    if tables:
        parts.append("\n## Tables\n")
        for i, table in enumerate(tables):
            if len(table.rows) > 0:
                parts.append(f"\n### Table {i + 1}\n")
                parts.append(table.to_markdown())
                parts.append("\n")
    
    return "\n".join(parts)


def _extract_narrative(text: str, tables: list[ExtractedTable]) -> str:
    """Extract narrative text, excluding table data."""
    # For now, return first 500 chars of narrative
    lines = text.split("\n")
    narrative_lines = []
    
    for line in lines[:30]:
        line = line.strip()
        if not line:
            continue
        
        # Skip lines that are mostly numbers (table rows)
        num_count = sum(1 for c in line if c.isdigit())
        if num_count > len(line) * 0.4:
            continue
        
        # Skip very short lines (likely table fragments)
        if len(line) < 10 and not line.endswith(":"):
            continue
        
        narrative_lines.append(line)
    
    return "\n".join(narrative_lines)

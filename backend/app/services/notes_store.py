"""
Notes Storage and Retrieval for Credit Analysis.

Architecture:
1. During document processing: Extract all notes -> Store as JSON in S3
2. During credit analysis: When a line item references "Note 3", retrieve just that note

Storage format (JSON):
{
    "document_id": "...",
    "scope": "GROUP",  
    "notes": {
        "3": {
            "title": "Property, plant and equipment",
            "pages": "25-26",
            "text": "Full note content...",
            "tables": [{"headers": [...], "rows": [...]}],
            "subsections": {
                "3.1": {"title": "Reconciliation", "text": "..."},
                "3.2": {"title": "Depreciation", "text": "..."}
            }
        },
        ...
    }
}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
import fitz


@dataclass
class NoteTable:
    """A table within a note."""
    headers: list[str]
    rows: list[list[str]]
    
    def to_dict(self) -> dict:
        return {"headers": self.headers, "rows": self.rows}
    
    def to_markdown(self) -> str:
        """Convert to markdown table format."""
        if not self.headers or not self.rows:
            return ""
        
        lines = []
        # Header
        lines.append("| " + " | ".join(self.headers) + " |")
        # Separator
        lines.append("|" + "|".join(["---" for _ in self.headers]) + "|")
        # Rows
        for row in self.rows:
            padded = row + [""] * (len(self.headers) - len(row))
            lines.append("| " + " | ".join(padded[:len(self.headers)]) + " |")
        return "\n".join(lines)


@dataclass
class NoteSection:
    note_id: str  # "3" or "3.1"
    title: str
    pages: str
    text: str
    tables: list[NoteTable] = field(default_factory=list)
    subsections: dict[str, "NoteSection"] | None = None
    
    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "pages": self.pages,
            "text": self.text,
            "tables": [t.to_dict() for t in self.tables],
        }
        if self.subsections:
            d["subsections"] = {k: v.to_dict() for k, v in self.subsections.items()}
        return d
    
    def to_formatted_text(self) -> str:
        """Get note as formatted text with tables in markdown."""
        parts = [f"## Note {self.note_id}: {self.title}"]
        parts.append(f"*Pages {self.pages}*\n")
        
        # Clean up the text for better readability
        clean_text = self._clean_text_for_llm(self.text)
        parts.append(clean_text)
        
        # Add markdown tables only if they have good data
        good_tables = [t for t in self.tables if self._is_good_table(t)]
        if good_tables:
            parts.append("\n### Extracted Tables\n")
            for i, table in enumerate(good_tables, 1):
                md = table.to_markdown()
                if md:
                    parts.append(f"\n**Table {i}:**\n{md}\n")
        
        return "\n".join(parts)
    
    def _clean_text_for_llm(self, text: str) -> str:
        """Clean raw text for better LLM readability."""
        lines = text.split("\n")
        cleaned = []
        prev_line = ""
        
        for line in lines:
            line = line.strip()
            if not line:
                if prev_line:  # Only one blank line
                    cleaned.append("")
                    prev_line = ""
                continue
            
            # Skip footer/header lines
            if "shoprite holdings" in line.lower() and "annual" in line.lower():
                continue
            if line.startswith("Corporate governance"):
                continue
            
            cleaned.append(line)
            prev_line = line
        
        return "\n".join(cleaned)
    
    def _is_good_table(self, table: "NoteTable") -> bool:
        """Check if a table has meaningful, properly-aligned data."""
        if len(table.rows) < 3:
            return False
        
        # Check if rows have data in value columns with proper alignment
        good_rows = 0
        for row in table.rows:
            if len(row) <= 1:
                continue
            
            # Check if item column is clean (not too long, no mixed content)
            item = row[0].strip() if row[0] else ""
            if len(item) > 60:  # Too long indicates mixed content
                return False
            
            # Check if value columns have clean numbers
            value_cells = [c.strip() for c in row[1:] if c.strip()]
            clean_values = 0
            for v in value_cells:
                # Clean value: numbers, parentheses, dashes, spaces only
                if re.match(r'^[\d\s\(\)—–\-,\.]+$', v) and len(v) < 20:
                    clean_values += 1
            
            if clean_values >= 1:
                good_rows += 1
        
        # At least 50% of rows should be well-formed
        return good_rows >= len(table.rows) * 0.5


def extract_notes_structured(pdf_bytes: bytes, scope: str = "GROUP") -> dict[str, NoteSection]:
    """
    Extract all notes from PDF by reading sequentially from notes section start to end.
    
    Simple approach:
    1. Find where notes start
    2. Read page by page
    3. When we see a new note number (1, 2, 3...), start a new note
    4. Subsections (1.1, 3.2, 9.1.2) are stored within their parent note
    
    Returns dict keyed by note number with subsections included.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Determine page range based on scope
    if scope == "GROUP":
        start_page, end_page = 12, 65  # Notes start on page 13 (index 12), end ~65
    else:
        start_page, end_page = 65, 75  # Company notes
    
    # Storage for notes
    notes: dict[str, NoteSection] = {}
    current_note_id: str | None = None
    current_note_title: str = ""
    current_note_start_page: int = 0
    current_note_content: list[str] = []
    current_subsections: dict[str, dict] = {}  # subsection_id -> {title, content}
    current_subsection_id: str | None = None
    
    def save_current_note():
        """Save the current note being built."""
        nonlocal current_note_id, current_note_content, current_subsections
        if current_note_id and current_note_content:
            # Build subsection objects
            subsections = {}
            for sub_id, sub_data in current_subsections.items():
                subsections[sub_id] = NoteSection(
                    note_id=sub_id,
                    title=sub_data["title"],
                    pages="",
                    text="\n".join(sub_data["content"]),
                )
            
            notes[current_note_id] = NoteSection(
                note_id=current_note_id,
                title=current_note_title,
                pages=f"{current_note_start_page}-{page_num}",
                text="\n".join(current_note_content),
                subsections=subsections if subsections else None,
            )
    
    # Read through all notes pages
    for page_idx in range(start_page, min(end_page, len(doc))):
        page = doc[page_idx]
        page_num = page_idx + 1
        page_width = page.rect.width
        mid_x = page_width / 2
        
        words = page.get_text("words", sort=True)
        
        # Detect if this is a two-column page
        # (significant words in both left and right halves)
        left_words = [w for w in words if w[0] < mid_x - 20]
        right_words = [w for w in words if w[0] > mid_x + 20]
        is_two_column = len(left_words) > 50 and len(right_words) > 50
        
        # For two-column pages, process left column then right column
        if is_two_column:
            columns = [
                [w for w in words if w[0] < mid_x],  # Left column
                [w for w in words if w[0] >= mid_x],  # Right column
            ]
        else:
            columns = [words]
        
        for col_idx, col_words in enumerate(columns):
            # Group words into lines
            lines: dict[int, list] = {}
            for w in col_words:
                x0, y0, x1, y1, text, *_ = w
                y_key = int(y0 // 4) * 4  # Group by ~4px
                if y_key not in lines:
                    lines[y_key] = []
                lines[y_key].append({"x0": x0, "x1": x1, "text": text})
            
            # For two-column pages in right column, adjust x threshold
            # Right column margin is around mid_x + small offset
            if col_idx == 0:
                x_threshold = 70
            else:
                # Right column - note numbers appear near mid_x
                x_threshold = mid_x + 70
            
            # Process lines in order
            for y_key in sorted(lines.keys()):
                line_words = sorted(lines[y_key], key=lambda w: w["x0"])
                if not line_words:
                    continue
                
                first_word = line_words[0]
                first_text = first_word["text"]
                first_x = first_word["x0"]
                
                # Skip header/footer lines
                line_text = " ".join(w["text"] for w in line_words)
                if "shoprite holdings" in line_text.lower() and "annual" in line_text.lower():
                    continue
                if "corporate governance" in line_text.lower():
                    continue
                
                # Check for new main note (single digit 1-50 at left margin of column)
                if first_x < x_threshold and re.match(r'^(\d{1,2})$', first_text):
                    note_num = int(first_text)
                    if 1 <= note_num <= 50:
                        # Get title from rest of line
                        title_words = [w["text"] for w in line_words[1:]]
                        title = " ".join(title_words).strip()
                        
                        # Clean up title - remove "continued"
                        clean_title = re.sub(r'\s*continued\s*', '', title, flags=re.IGNORECASE).strip()
                        
                        # If we're already tracking this note, skip (it's a "continued" page)
                        if current_note_id == first_text:
                            continue
                        
                        # If this is a new note number
                        if clean_title and current_note_id != first_text:
                            # Save previous note
                            save_current_note()
                            
                            # Start new note
                            current_note_id = first_text
                            current_note_title = clean_title
                            current_note_start_page = page_num
                            current_note_content = [f"{first_text} {clean_title}"]
                            current_subsections = {}
                            current_subsection_id = None
                            continue
                
                # Check for subsection (e.g., 1.1, 3.2, 9.1.2)
                if first_x < x_threshold + 10 and re.match(r'^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)$', first_text):
                    subsection_id = first_text
                    base_note = subsection_id.split(".")[0]
                    
                    # Only track if we're in this note
                    if current_note_id == base_note:
                        title_words = [w["text"] for w in line_words[1:]]
                        title = " ".join(title_words).strip()
                        
                        if title and "continued" not in title.lower():
                            current_subsection_id = subsection_id
                            current_subsections[subsection_id] = {
                                "title": title,
                                "content": [f"{subsection_id} {title}"]
                            }
                            current_note_content.append(f"\n### {subsection_id} {title}")
                            continue
                
                # Regular content line - add to current note/subsection
                if current_note_id:
                    content_line = line_text.strip()
                    if content_line:
                        current_note_content.append(content_line)
                        
                        # Also add to current subsection if active
                        if current_subsection_id and current_subsection_id in current_subsections:
                            current_subsections[current_subsection_id]["content"].append(content_line)
    
    # Save the last note
    save_current_note()
    
    doc.close()
    return notes


def _extract_tables_for_note(
    doc: fitz.Document, 
    start_page: int, 
    end_page: int,
    note_id: str,
) -> list[NoteTable]:
    """
    Extract tables from a note's page range.
    
    Uses coordinate-based extraction to properly align columns.
    """
    tables: list[NoteTable] = []
    
    for page_idx in range(start_page - 1, min(end_page, len(doc))):
        page = doc[page_idx]
        words = page.get_text("words", sort=True)
        
        if not words:
            continue
        
        # Group by y-position (with tolerance)
        lines: dict[int, list] = {}
        for w in words:
            x0, y0, x1, y1, text, *_ = w
            y_key = int(y0 // 3) * 3  # Round to 3px groups for line detection
            if y_key not in lines:
                lines[y_key] = []
            lines[y_key].append({
                "x0": x0, "x1": x1, "y0": y0, "text": text,
                "x_center": (x0 + x1) / 2
            })
        
        sorted_y = sorted(lines.keys())
        
        # Find table header rows (contain "Rm" or multiple year patterns)
        i = 0
        while i < len(sorted_y):
            y = sorted_y[i]
            line_words = lines[y]
            
            rm_words = [w for w in line_words if w["text"].lower() == "rm"]
            year_words = [w for w in line_words if re.match(r"^20\d{2}\*?$", w["text"])]
            
            # Require multiple Rm headers or years to indicate a real table
            if len(rm_words) >= 2 or len(year_words) >= 2:
                table = _extract_table_with_smart_columns(lines, sorted_y, i)
                if table and len(table.rows) >= 2:
                    tables.append(table)
                    # Skip past this table
                    i += len(table.rows) + 1
                    continue
            i += 1
    
    return tables


def _extract_table_with_smart_columns(
    lines: dict[int, list],
    sorted_y: list[int],
    header_idx: int,
) -> NoteTable | None:
    """
    Extract a table with intelligent column detection.
    
    Detects column positions based on header "Rm" or year tokens,
    then assigns values to columns based on x-proximity.
    """
    if header_idx >= len(sorted_y):
        return None
    
    header_y = sorted_y[header_idx]
    header_words = sorted(lines[header_y], key=lambda w: w["x0"])
    
    # Find value column positions from Rm/year headers
    value_columns: list[tuple[str, float]] = []  # (name, x_center)
    
    for w in header_words:
        text = w["text"]
        if text.lower() == "rm" or re.match(r"^20\d{2}\*?$", text):
            value_columns.append((text, w["x_center"]))
    
    if len(value_columns) < 2:
        return None
    
    # Sort columns by x position
    value_columns.sort(key=lambda c: c[1])
    
    # Build column structure: Label column + value columns
    headers = ["Item"] + [c[0] for c in value_columns]
    
    # Calculate column boundaries
    label_end = value_columns[0][1] - 30
    col_boundaries = [label_end]  # End of label column
    
    for i in range(len(value_columns) - 1):
        mid = (value_columns[i][1] + value_columns[i + 1][1]) / 2
        col_boundaries.append(mid)
    col_boundaries.append(9999)  # Last column extends to page edge
    
    rows: list[list[str]] = []
    
    # Extract rows
    for i in range(header_idx + 1, min(header_idx + 40, len(sorted_y))):
        y = sorted_y[i]
        line_words = sorted(lines[y], key=lambda w: w["x0"])
        
        # Skip empty lines
        if not line_words:
            continue
        
        # Build row by assigning words to columns
        row = [""] * len(headers)
        
        for w in line_words:
            x_center = w["x_center"]
            text = w["text"]
            
            # Determine which column
            col_idx = 0
            if x_center < col_boundaries[0]:
                col_idx = 0  # Label column
            else:
                for j in range(len(col_boundaries) - 1):
                    if col_boundaries[j] <= x_center < col_boundaries[j + 1]:
                        col_idx = j + 1
                        break
            
            if row[col_idx]:
                row[col_idx] += " " + text
            else:
                row[col_idx] = text
        
        # Check if row has content
        if any(cell.strip() for cell in row):
            # Check for end of table (multiple text-only rows)
            has_values = any(
                re.search(r"\d", cell) for cell in row[1:]
            )
            if not has_values and row[0]:
                # Text-only row - check if it's a section header or end
                label = row[0].lower()
                if "note" in label and re.search(r"\d", label):
                    break  # End at note references
            
            rows.append(row)
    
    return NoteTable(headers=headers, rows=rows)


def notes_to_json(notes: dict[str, NoteSection]) -> str:
    """Convert notes dict to JSON string for storage."""
    return json.dumps(
        {note_id: note.to_dict() for note_id, note in notes.items()},
        indent=2,
        ensure_ascii=False,
    )


def notes_from_json(json_str: str) -> dict[str, NoteSection]:
    """Load notes from JSON string."""
    data = json.loads(json_str)
    notes = {}
    for note_id, note_data in data.items():
        # Parse tables if present
        tables = []
        for t_data in note_data.get("tables", []):
            tables.append(NoteTable(
                headers=t_data.get("headers", []),
                rows=t_data.get("rows", []),
            ))
        
        notes[note_id] = NoteSection(
            note_id=note_id,
            title=note_data["title"],
            pages=note_data["pages"],
            text=note_data["text"],
            tables=tables,
            subsections=None,
        )
    return notes


def get_note_for_llm(notes: dict[str, NoteSection], note_ref: str) -> str | None:
    """
    Retrieve a specific note for LLM context.
    
    Args:
        notes: Dict of all notes (loaded from storage)
        note_ref: Note reference like "3", "9.1", "21"
    
    Returns:
        Formatted note text ready for LLM prompt (with tables as markdown), or None if not found
    """
    # Handle decimal notes (e.g., "38.1" -> look in note "38")
    base_note = note_ref.split(".")[0]
    
    if base_note not in notes:
        return None
    
    note = notes[base_note]
    
    # Use the formatted output with tables
    return note.to_formatted_text()


def get_notes_for_line_items(
    notes: dict[str, NoteSection],
    line_items: list[dict],
    max_notes: int = 10,
) -> str:
    """
    Given a list of line items (from statement extraction), retrieve all referenced notes.
    
    Args:
        notes: Dict of all notes
        line_items: List of extracted rows with "note" field
        max_notes: Maximum number of notes to include
    
    Returns:
        Combined notes text for LLM context
    """
    # Collect unique note references
    note_refs = set()
    for item in line_items:
        note = item.get("note")
        if note:
            # Handle decimal notes
            base_note = str(note).split(".")[0]
            note_refs.add(base_note)
    
    if not note_refs:
        return ""
    
    # Sort by note number
    sorted_refs = sorted(note_refs, key=lambda x: int(x) if x.isdigit() else 999)[:max_notes]
    
    parts = ["# RELEVANT NOTES\n"]
    for ref in sorted_refs:
        note_text = get_note_for_llm(notes, ref)
        if note_text:
            parts.append(note_text)
            parts.append("\n---\n")
    
    return "\n".join(parts)


# S3 Storage functions (integrate with your existing storage.py)
def store_notes_to_s3(
    storage_client,
    document_version_id: str,
    notes: dict[str, NoteSection],
    scope: str = "GROUP",
) -> str:
    """
    Store notes JSON to S3.
    Returns the S3 key where notes were stored.
    """
    from app.services.storage import get_storage_client
    
    json_content = notes_to_json(notes)
    key = f"notes/{document_version_id}/{scope}_notes.json"
    
    storage_client.put_object(
        key=key,
        body=json_content.encode("utf-8"),
        content_type="application/json",
    )
    
    return key


def load_notes_from_s3(
    storage_client,
    document_version_id: str,
    scope: str = "GROUP",
) -> dict[str, NoteSection] | None:
    """
    Load notes JSON from S3.
    Returns notes dict or None if not found.
    """
    key = f"notes/{document_version_id}/{scope}_notes.json"
    
    try:
        response = storage_client.get_object(key=key)
        json_content = response["Body"].read().decode("utf-8")
        return notes_from_json(json_content)
    except Exception:
        return None

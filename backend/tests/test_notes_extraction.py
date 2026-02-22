"""
Test script to extract notes from PDF in an organized manner for LLM consumption.

Outputs a structured text file with:
1. Notes index (note number -> title -> page range)
2. Full text content of each note, organized by note number
3. Summary of which notes are referenced by which line items

Usage:
    python tests/test_notes_extraction.py
"""
import sys
import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import fitz  # PyMuPDF


@dataclass
class NoteEntry:
    note_number: str
    title: str
    start_page: int
    end_page: int
    text: str = ""


def extract_notes_index(pdf_bytes: bytes) -> list[NoteEntry]:
    """
    Extract notes index from the PDF using position-based detection.
    Scans pages for note headers (number + title at left margin).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    entries: list[NoteEntry] = []
    seen_notes = set()
    
    # Scan pages 22-130 (where notes typically are in annual reports)
    for page_idx in range(21, min(130, len(doc))):
        page = doc[page_idx]
        words = page.get_text("words", sort=True)
        
        # Group words by y-position (same line)
        lines: dict[int, list] = {}
        for w in words:
            x0, y0, x1, y1, text, *_ = w
            y_key = int(y0)
            if y_key not in lines:
                lines[y_key] = []
            lines[y_key].append((x0, text))
        
        # Look for note headers: single digit 1-50 at left margin (x < 70)
        # followed by title words on the same line
        for y_key, line_words in lines.items():
            line_words.sort(key=lambda w: w[0])  # Sort by x position
            
            if not line_words:
                continue
            
            first_x, first_text = line_words[0]
            
            # Check if first word is a note number at left margin
            if first_x < 70 and first_text.isdigit() and 1 <= int(first_text) <= 50:
                note_num = first_text
                
                # Skip if already found
                if note_num in seen_notes:
                    continue
                
                # Get title from remaining words on this line
                title_words = []
                for x, text in line_words[1:]:
                    # Stop at numbers (likely values) or special chars
                    if text.replace(',', '').replace('.', '').isdigit():
                        break
                    if x > 400:  # Stop if too far right (likely values)
                        break
                    title_words.append(text)
                
                title = " ".join(title_words).strip()
                
                # Validate title
                if len(title) < 3:
                    continue
                if title.lower() in ['rm', 'notes', 'continued', 'restated']:
                    continue
                
                seen_notes.add(note_num)
                entries.append(NoteEntry(
                    note_number=note_num,
                    title=title,
                    start_page=page_idx + 1,
                    end_page=page_idx + 1,
                ))
    
    doc.close()
    
    # Sort by note number
    entries.sort(key=lambda e: int(e.note_number))
    
    # Infer end pages from next entry
    for i in range(len(entries) - 1):
        entries[i].end_page = entries[i + 1].start_page - 1
        if entries[i].end_page < entries[i].start_page:
            entries[i].end_page = entries[i].start_page
    
    # Last entry ends at last page before company statements (around page 65)
    if entries:
        entries[-1].end_page = min(entries[-1].start_page + 5, 65)
    
    return entries


def extract_note_content(pdf_bytes: bytes, note: NoteEntry) -> str:
    """
    Extract the text content for a specific note from its page range.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    content_parts = []
    
    start_page = note.start_page - 1  # 0-indexed
    end_page = min(note.end_page, len(doc)) - 1
    
    for page_idx in range(start_page, end_page + 1):
        if page_idx < 0 or page_idx >= len(doc):
            continue
        page = doc[page_idx]
        text = page.get_text()
        content_parts.append(text)
    
    doc.close()
    
    full_text = "\n".join(content_parts)
    
    # Try to find and extract just this note's content
    # Look for the note header pattern: "21. Borrowings" or "Note 21 Borrowings"
    note_header = rf"(?:Note\s+)?{note.note_number}[\.\s\-–—]+\s*{re.escape(note.title[:20])}"
    next_note = rf"(?:Note\s+)?{int(note.note_number) + 1}[\.\s\-–—]+"
    
    # Find start of this note
    start_match = re.search(note_header, full_text, re.IGNORECASE)
    if start_match:
        text_from_start = full_text[start_match.start():]
        
        # Find start of next note (if exists)
        end_match = re.search(next_note, text_from_start[100:], re.IGNORECASE)
        if end_match:
            return text_from_start[:100 + end_match.start()].strip()
        return text_from_start.strip()
    
    return full_text.strip()


def extract_referenced_notes_from_statements(pdf_bytes: bytes) -> dict[str, list[str]]:
    """
    Extract which notes are referenced by each financial statement.
    Returns {statement_type: [note_numbers]}
    """
    from app.services.statement_geometry_extractor import extract_statement_geometry
    from app.services.soce_geometry_extractor import extract_soce_geometry
    
    references: dict[str, set[str]] = {
        "SFP": set(),
        "SCI": set(),
        "CF": set(),
        "SOCE": set(),
    }
    
    # Known statement pages for this PDF
    statement_pages = {
        "SFP": [11, 67],
        "SCI": [11, 67],
        "CF": [12, 68],
        "SOCE": [12, 68],
    }
    
    for stmt_type, pages in statement_pages.items():
        for page_no in pages:
            try:
                if stmt_type == "SOCE":
                    _, _, rows = extract_soce_geometry(pdf_bytes, page_no)
                else:
                    _, _, _, rows = extract_statement_geometry(pdf_bytes, page_no, stmt_type)
                
                for row in rows:
                    note = row.get("note")
                    if note:
                        # Handle decimal notes like "38.1" -> "38"
                        note_num = str(note).split(".")[0]
                        references[stmt_type].add(note_num)
            except Exception as e:
                print(f"  Warning: Could not extract {stmt_type} from page {page_no}: {e}")
    
    return {k: sorted(v, key=lambda x: int(x) if x.isdigit() else 999) for k, v in references.items()}


def format_notes_for_llm(
    notes: list[NoteEntry],
    referenced_notes: dict[str, list[str]],
    include_full_text: bool = False,
) -> str:
    """
    Format notes in a structured way for LLM consumption.
    """
    lines = []
    lines.append("=" * 80)
    lines.append("NOTES TO THE FINANCIAL STATEMENTS")
    lines.append("=" * 80)
    lines.append("")
    
    # Section 1: Notes Index
    lines.append("## NOTES INDEX")
    lines.append("-" * 40)
    for note in notes:
        lines.append(f"Note {note.note_number}: {note.title} (pages {note.start_page}-{note.end_page})")
    lines.append("")
    
    # Section 2: Statement References
    lines.append("## NOTES REFERENCED BY STATEMENT")
    lines.append("-" * 40)
    for stmt_type, note_nums in referenced_notes.items():
        if note_nums:
            lines.append(f"{stmt_type}: Notes {', '.join(note_nums)}")
    lines.append("")
    
    # Section 3: All unique referenced notes
    all_referenced = set()
    for notes_list in referenced_notes.values():
        all_referenced.update(notes_list)
    
    lines.append("## REFERENCED NOTES (sorted)")
    lines.append("-" * 40)
    
    for note_num in sorted(all_referenced, key=lambda x: int(x) if x.isdigit() else 999):
        note = next((n for n in notes if n.note_number == note_num), None)
        if note:
            lines.append(f"Note {note.note_number}: {note.title}")
            
            # Show which statements reference this note
            referencing = [s for s, nums in referenced_notes.items() if note_num in nums]
            lines.append(f"  Referenced by: {', '.join(referencing)}")
            
            if include_full_text and note.text:
                lines.append("")
                lines.append("  Content:")
                lines.append("  " + "-" * 60)
                # Indent and truncate content
                content_lines = note.text.split("\n")
                for cl in content_lines[:100]:  # Max 100 lines per note
                    lines.append(f"  {cl}")
                if len(content_lines) > 100:
                    lines.append("  [...truncated...]")
                lines.append("")
        else:
            lines.append(f"Note {note_num}: (not found in index)")
    
    lines.append("")
    lines.append("=" * 80)
    lines.append("END OF NOTES")
    lines.append("=" * 80)
    
    return "\n".join(lines)


def format_notes_compact(
    notes: list[NoteEntry],
    referenced_notes: dict[str, list[str]],
) -> str:
    """
    Format notes in a compact way for token-efficient LLM prompts.
    Only includes note titles and first paragraph of content.
    """
    lines = []
    lines.append("# NOTES SUMMARY")
    lines.append("")
    
    # All unique referenced notes
    all_referenced = set()
    for notes_list in referenced_notes.values():
        all_referenced.update(notes_list)
    
    for note_num in sorted(all_referenced, key=lambda x: int(x) if x.isdigit() else 999):
        note = next((n for n in notes if n.note_number == note_num), None)
        if note:
            lines.append(f"## Note {note.note_number}: {note.title}")
            lines.append(f"Pages: {note.start_page}-{note.end_page}")
            
            # Show which statements reference this note
            referencing = [s for s, nums in referenced_notes.items() if note_num in nums]
            lines.append(f"Used by: {', '.join(referencing)}")
            
            if note.text:
                # Get first 500 characters as summary
                summary = note.text[:500].replace('\n', ' ').strip()
                if len(note.text) > 500:
                    summary += "..."
                lines.append(f"Summary: {summary}")
            lines.append("")
        else:
            lines.append(f"## Note {note_num}: (not in index)")
            referencing = [s for s, nums in referenced_notes.items() if note_num in nums]
            lines.append(f"Used by: {', '.join(referencing)}")
            lines.append("")
    
    return "\n".join(lines)


def test_notes_extraction(
    pdf_path: str,
    output_dir: str = None,
    include_full_text: bool = True,
):
    """
    Extract notes from PDF and save to organized text file.
    Creates both full and compact versions.
    """
    if output_dir is None:
        output_dir = backend_dir.parent / "test_results"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(exist_ok=True)
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        return
    
    print("=" * 60)
    print("NOTES EXTRACTION TEST")
    print("=" * 60)
    print(f"Reading PDF: {pdf_path}")
    
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    
    # Step 1: Extract notes index
    print("\n1. Extracting notes index...")
    notes = extract_notes_index(pdf_bytes)
    print(f"   Found {len(notes)} notes in index")
    
    if notes:
        print("   First 10 notes:")
        for note in notes[:10]:
            print(f"     Note {note.note_number}: {note.title} (p{note.start_page})")
    
    # Step 2: Extract which notes are referenced by statements
    print("\n2. Extracting note references from statements...")
    referenced_notes = extract_referenced_notes_from_statements(pdf_bytes)
    for stmt, refs in referenced_notes.items():
        print(f"   {stmt}: {len(refs)} notes referenced")
    
    # Step 3: Extract content for referenced notes
    all_referenced = set()
    for refs in referenced_notes.values():
        all_referenced.update(refs)
    
    print(f"\n3. Extracting content for {len(all_referenced)} referenced notes...")
    for note in notes:
        if note.note_number in all_referenced:
            print(f"   Extracting Note {note.note_number}...")
            note.text = extract_note_content(pdf_bytes, note)
            print(f"     -> {len(note.text)} characters")
    
    # Step 4: Format and save FULL version
    print("\n4. Formatting notes for LLM...")
    formatted = format_notes_for_llm(notes, referenced_notes, include_full_text)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"notes_{pdf_path.stem}_{timestamp}.txt"
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(formatted)
    
    print(f"   Full version: {output_file.stat().st_size:,} bytes")
    
    # Step 5: Create COMPACT version for token-efficient prompts
    compact = format_notes_compact(notes, referenced_notes)
    compact_file = output_dir / f"notes_compact_{pdf_path.stem}_{timestamp}.txt"
    
    with open(compact_file, "w", encoding="utf-8") as f:
        f.write(compact)
    
    print(f"   Compact version: {compact_file.stat().st_size:,} bytes")
    
    print(f"\n" + "=" * 60)
    print(f"NOTES SAVED TO:")
    print(f"  Full: {output_file}")
    print(f"  Compact: {compact_file}")
    print("=" * 60)
    
    # Also print summary
    print("\n## SUMMARY")
    print(f"Total notes in index: {len(notes)}")
    print(f"Notes referenced by statements: {len(all_referenced)}")
    for stmt, refs in referenced_notes.items():
        if refs:
            print(f"  {stmt}: {', '.join(refs)}")
    
    return output_file, compact_file


if __name__ == "__main__":
    # Default PDF path
    default_pdf = backend_dir.parent / "shp-afs-2025.pdf"
    
    # Allow override via command line
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = str(default_pdf)
    
    test_notes_extraction(pdf_path, include_full_text=True)

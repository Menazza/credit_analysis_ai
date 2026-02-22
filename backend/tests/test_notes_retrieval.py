"""
Test the notes storage and retrieval system.

Demonstrates the workflow:
1. Extract notes from PDF -> Store as JSON
2. When analyzing a line item with "note: 3" -> Retrieve just Note 3
3. Pass only relevant notes to LLM (not all 40KB)
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.notes_store import (
    extract_notes_structured,
    notes_to_json,
    notes_from_json,
    get_note_for_llm,
    get_notes_for_line_items,
)


def test_notes_workflow():
    """Test the full notes extraction and retrieval workflow."""
    
    pdf_path = backend_dir.parent / "shp-afs-2025.pdf"
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        return
    
    print("=" * 60)
    print("NOTES RETRIEVAL SYSTEM TEST")
    print("=" * 60)
    
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    
    # Step 1: Extract all notes
    print("\n1. Extracting notes from PDF...")
    notes = extract_notes_structured(pdf_bytes, scope="GROUP")
    print(f"   Extracted {len(notes)} notes")
    
    # Show what was extracted
    print("\n   Notes found:")
    for note_id in sorted(notes.keys(), key=lambda x: int(x)):
        note = notes[note_id]
        print(f"     Note {note_id}: {note.title} ({len(note.text)} chars)")
    
    # Step 2: Convert to JSON (this would be stored in S3)
    print("\n2. Converting to JSON for storage...")
    json_str = notes_to_json(notes)
    print(f"   JSON size: {len(json_str):,} bytes")
    
    # Save to file for inspection
    output_dir = backend_dir.parent / "test_results"
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / "notes_structured.json"
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    print(f"   Saved to: {json_path}")
    
    # Step 3: Simulate loading from storage
    print("\n3. Simulating load from S3...")
    loaded_notes = notes_from_json(json_str)
    print(f"   Loaded {len(loaded_notes)} notes")
    
    # Step 4: Test single note retrieval
    print("\n4. Testing single note retrieval:")
    
    for note_ref in ["3", "9", "21", "38.1"]:
        note_text = get_note_for_llm(loaded_notes, note_ref)
        if note_text:
            lines = note_text.split("\n")
            preview = lines[0] + "..." if lines else "(empty)"
            print(f"   Note {note_ref}: {len(note_text)} chars - {preview}")
        else:
            print(f"   Note {note_ref}: NOT FOUND")
    
    # Step 5: Test retrieval for line items (simulating credit analysis)
    print("\n5. Simulating credit analysis retrieval:")
    
    # Fake line items from SFP extraction
    sfp_items = [
        {"raw_label": "Property, plant and equipment", "note": "3", "2025": 22536},
        {"raw_label": "Investment properties", "note": "5", "2025": 128},
        {"raw_label": "Equity accounted investments", "note": "9", "2025": 2452},
        {"raw_label": "Current assets", "note": None, "2025": 15000},
        {"raw_label": "Borrowings", "note": "21", "2025": 5000},
    ]
    
    print("   Line items being analyzed:")
    for item in sfp_items:
        print(f"     - {item['raw_label']}: note={item['note']}")
    
    context = get_notes_for_line_items(loaded_notes, sfp_items)
    print(f"\n   Retrieved notes context: {len(context):,} chars")
    print(f"   (vs full notes JSON: {len(json_str):,} chars)")
    print(f"   Reduction: {(1 - len(context)/len(json_str))*100:.1f}%")
    
    # Save the context that would go to LLM
    context_path = output_dir / "notes_context_for_llm.txt"
    with open(context_path, "w", encoding="utf-8") as f:
        f.write(context)
    print(f"\n   Saved LLM context to: {context_path}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    
    # Show the actual context
    print("\n## SAMPLE LLM CONTEXT (first 2000 chars):\n")
    print(context[:2000])
    if len(context) > 2000:
        print(f"\n... [{len(context) - 2000} more characters]")


if __name__ == "__main__":
    test_notes_workflow()

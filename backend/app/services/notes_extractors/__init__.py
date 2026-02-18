"""
Strict note extractors: DEBT (Borrowings), LEASES, CONTINGENCIES, RISK.
Each returns structured JSON with provenance.
"""
from app.services.notes_extractors.base import extract_note_by_type

__all__ = ["extract_note_by_type"]

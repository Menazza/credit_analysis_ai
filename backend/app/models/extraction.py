from sqlalchemy import Column, String, Integer, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base_class import BaseModel
from app.db.session import Base

try:
    from pgvector.sqlalchemy import Vector
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False


class PresentationContext(Base, BaseModel):
    __tablename__ = "presentation_contexts"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    scope = Column(String(50), nullable=False)  # DOC, STATEMENT, NOTE
    scope_key = Column(String(100), nullable=True)  # SFP, Note16, etc.
    currency = Column(String(3), nullable=True)
    scale = Column(String(50), nullable=True)  # Rm, R'000
    scale_factor = Column(Float, nullable=True)  # 1e6, 1e3
    period_weeks = Column(Integer, nullable=True)
    evidence_json = Column(JSONB, default=dict)
    document_version = relationship("DocumentVersion", back_populates="presentation_contexts")


class Statement(Base, BaseModel):
    __tablename__ = "statements"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    statement_type = Column(String(20), nullable=False)  # SFP, SCI, CF, SoCE
    entity_scope = Column(String(20), default="GROUP")  # GROUP, COMPANY
    periods_json = Column(JSONB, default=list)  # [{"label": "2024", "end_date": "2024-06-30"}, ...]
    document_version = relationship("DocumentVersion", back_populates="statements")
    lines = relationship("StatementLine", back_populates="statement")


class StatementLine(Base, BaseModel):
    __tablename__ = "statement_lines"
    statement_id = Column(UUID(as_uuid=True), ForeignKey("statements.id"), nullable=False)
    line_no = Column(Integer, nullable=False)
    raw_label = Column(String(500), nullable=False)
    section_path = Column(String(200), nullable=True)  # Assets>Current
    note_refs_json = Column(JSONB, default=list)
    values_json = Column(JSONB, default=dict)  # {period_key: value}
    evidence_json = Column(JSONB, default=dict)  # page, bbox, source_file
    statement = relationship("Statement", back_populates="lines")


class NotesIndex(Base, BaseModel):
    __tablename__ = "notes_index"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    note_number = Column(String(20), nullable=True)
    title = Column(String(500), nullable=True)
    start_page = Column(Integer, nullable=True)
    end_page = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    document_version = relationship("DocumentVersion", back_populates="notes_index_entries")


class NoteExtraction(Base, BaseModel):
    __tablename__ = "note_extractions"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    note_number = Column(String(20), nullable=True)
    title = Column(String(500), nullable=True)
    blocks_json = Column(JSONB, default=list)
    tables_json = Column(JSONB, default=list)
    presentation_context_id = Column(UUID(as_uuid=True), ForeignKey("presentation_contexts.id"), nullable=True)
    evidence_json = Column(JSONB, default=dict)
    document_version = relationship("DocumentVersion", back_populates="note_extractions")


class NoteChunk(Base, BaseModel):
    """Chunk of note text for on-demand retrieval. Stable IDs: note_id (GROUP:21), chunk_id (GROUP:21.1)."""
    __tablename__ = "note_chunks"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    scope = Column(String(20), nullable=False)  # GROUP, COMPANY
    note_id = Column(String(50), nullable=False)  # e.g. GROUP:21
    chunk_id = Column(String(80), nullable=False)  # e.g. GROUP:21.1
    title = Column(String(500), nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    text = Column(String, nullable=True)  # Text content
    tables_json = Column(JSONB, default=list)
    tokens_approx = Column(Integer, nullable=True)
    keywords_json = Column(JSONB, default=list)
    document_version = relationship("DocumentVersion", back_populates="note_chunks")


# Add embedding column when pgvector is available (migration creates the DB column)
if _HAS_PGVECTOR:
    NoteChunk.__table__.append_column(Column("embedding", Vector(1536), nullable=True))

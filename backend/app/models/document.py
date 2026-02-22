from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base_class import BaseModel
from app.db.session import Base


class Document(Base, BaseModel):
    __tablename__ = "documents"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    # Optional engagement context so documents are scoped to a specific review/workspace
    engagement_id = Column(UUID(as_uuid=True), ForeignKey("engagements.id"), nullable=True)
    doc_type = Column(String(50), nullable=False)  # AFS, MA, TB, DEBT_SCHEDULE, COV_CERT, FORECAST, etc.
    original_filename = Column(String(500), nullable=False)
    storage_url = Column(String(1000), nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    company = relationship("Company", back_populates="documents")
    engagement = relationship("Engagement", back_populates="documents", uselist=False)
    versions = relationship("DocumentVersion", back_populates="document")


class DocumentVersion(Base, BaseModel):
    __tablename__ = "document_versions"
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    sha256 = Column(String(64), nullable=True)
    parser_version = Column(String(50), nullable=True)
    status = Column(String(50), default="PENDING")  # PENDING, INGESTING, EXTRACTING, MAPPED, FAILED
    document = relationship("Document", back_populates="versions")
    page_assets = relationship("PageAsset", back_populates="document_version")
    presentation_contexts = relationship("PresentationContext", back_populates="document_version")
    statements = relationship("Statement", back_populates="document_version")
    notes_index_entries = relationship("NotesIndex", back_populates="document_version")
    note_extractions = relationship("NoteExtraction", back_populates="document_version")
    note_chunks = relationship("NoteChunk", back_populates="document_version")
    validation_reports = relationship("ValidationReport", back_populates="document_version")


class PageAsset(Base, BaseModel):
    __tablename__ = "page_assets"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    page_no = Column(Integer, nullable=False)
    image_url = Column(String(1000), nullable=True)
    tokens_json_url = Column(String(1000), nullable=True)
    text_hash = Column(String(64), nullable=True)
    document_version = relationship("DocumentVersion", back_populates="page_assets")
    layouts = relationship("PageLayout", back_populates="page_asset")


class PageLayout(Base, BaseModel):
    __tablename__ = "page_layouts"
    page_asset_id = Column(UUID(as_uuid=True), ForeignKey("page_assets.id"), nullable=False)
    regions_json = Column(JSONB, default=list)  # [{bbox, label, confidence}, ...]
    page_asset = relationship("PageAsset", back_populates="layouts")

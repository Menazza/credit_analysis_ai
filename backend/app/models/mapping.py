from sqlalchemy import Column, String, ForeignKey, Date, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base_class import BaseModel
from app.db.session import Base


class CanonicalAccount(Base, BaseModel):
    __tablename__ = "canonical_accounts"
    canonical_key = Column(String(100), nullable=False, unique=True)
    statement_type = Column(String(20), nullable=False)  # SFP, SCI, CF, SoCE
    display_name = Column(String(200), nullable=True)
    description = Column(String(500), nullable=True)
    allow_negative = Column(String(10), default="true")
    tags_json = Column(JSONB, default=list)


class MappingDecision(Base, BaseModel):
    __tablename__ = "mapping_decisions"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    raw_label_hash = Column(String(64), nullable=False)
    raw_label = Column(String(500), nullable=False)
    statement_type = Column(String(20), nullable=False)
    canonical_key = Column(String(100), nullable=False)
    confidence = Column(Float, nullable=True)
    method = Column(String(20), default="LLM")  # LLM, RULE, MANUAL
    rationale = Column(String(500), nullable=True)
    evidence_json = Column(JSONB, default=dict)


class ValidationReport(Base, BaseModel):
    __tablename__ = "validation_reports"
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    status = Column(String(20), nullable=False)  # PASS, FAIL, WARN
    checks_json = Column(JSONB, default=list)
    failures_json = Column(JSONB, default=list)
    document_version = relationship("DocumentVersion", back_populates="validation_reports")


class NormalizedFact(Base, BaseModel):
    __tablename__ = "normalized_facts"
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    period_end = Column(Date, nullable=False)
    statement_type = Column(String(20), nullable=False)
    canonical_key = Column(String(100), nullable=False)
    value_base = Column(Float, nullable=False)  # in base currency units
    value_original = Column(Float, nullable=True)
    unit_meta_json = Column(JSONB, default=dict)
    source_refs_json = Column(JSONB, default=list)  # evidence refs
    company = relationship("Company", back_populates="normalized_facts")

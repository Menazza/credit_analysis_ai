"""
MappingRule, UnmappedLabel, PipelineRun models for Track 3 & 4.
"""
from sqlalchemy import Column, String, ForeignKey, Integer, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.db.base_class import BaseModel
from app.db.session import Base


class MappingRule(Base, BaseModel):
    __tablename__ = "mapping_rules"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    pattern = Column(String(500), nullable=False)
    canonical_key = Column(String(100), nullable=False)
    scope = Column(String(50), nullable=False, server_default="global")
    scope_entity_id = Column(UUID(as_uuid=True), nullable=True)
    priority = Column(Integer, nullable=False, server_default="100")
    created_by = Column(UUID(as_uuid=True), nullable=True)
    is_expense = Column(Boolean, server_default="false")


class UnmappedLabel(Base, BaseModel):
    __tablename__ = "unmapped_labels"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_version_id = Column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    raw_label = Column(String(500), nullable=False)
    sheet = Column(String(100), nullable=True)
    occurrence_count = Column(Integer, server_default="1")


class PipelineRun(Base, BaseModel):
    __tablename__ = "pipeline_runs"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    credit_review_version_id = Column(UUID(as_uuid=True), ForeignKey("credit_review_versions.id"), nullable=True)
    stage = Column(String(50), nullable=False)
    input_hash = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, server_default="running")
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(String(2000), nullable=True)
    artifact_ids_json = Column(JSONB, default=lambda: [])
    counts_json = Column(JSONB, default=lambda: {})

from sqlalchemy import Column, String, ForeignKey, Date, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base_class import BaseModel
from app.db.session import Base


class MetricFact(Base, BaseModel):
    __tablename__ = "metric_facts"
    credit_review_version_id = Column(UUID(as_uuid=True), ForeignKey("credit_review_versions.id"), nullable=False)
    metric_key = Column(String(100), nullable=False)
    value = Column(Float, nullable=False)
    period_end = Column(Date, nullable=True)
    calc_trace_json = Column(JSONB, default=list)  # audit trail
    credit_review_version = relationship("CreditReviewVersion", back_populates="metric_facts")


class RatingModel(Base, BaseModel):
    __tablename__ = "rating_models"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name = Column(String(200), nullable=False)
    version = Column(String(50), nullable=False)
    config_json = Column(JSONB, default=dict)
    rating_results = relationship("RatingResult", back_populates="model")


class RatingResult(Base, BaseModel):
    __tablename__ = "rating_results"
    credit_review_version_id = Column(UUID(as_uuid=True), ForeignKey("credit_review_versions.id"), nullable=False)
    model_id = Column(UUID(as_uuid=True), ForeignKey("rating_models.id"), nullable=False)
    rating_grade = Column(String(20), nullable=True)
    pd_band = Column(Float, nullable=True)
    score_breakdown_json = Column(JSONB, default=dict)
    overrides_json = Column(JSONB, default=dict)
    rationale_json = Column(JSONB, default=dict)
    credit_review_version = relationship("CreditReviewVersion", back_populates="rating_results")
    model = relationship("RatingModel", back_populates="rating_results")


class CommentaryBlock(Base, BaseModel):
    __tablename__ = "commentary_blocks"
    credit_review_version_id = Column(UUID(as_uuid=True), ForeignKey("credit_review_versions.id"), nullable=False)
    section_key = Column(String(100), nullable=False)
    text = Column(String(10000), nullable=True)
    sources_json = Column(JSONB, default=list)
    generated_by = Column(String(20), default="MANUAL")  # LLM, MANUAL
    locked = Column(String(10), default="false")
    credit_review_version = relationship("CreditReviewVersion", back_populates="commentary_blocks")


class ExportArtifact(Base, BaseModel):
    __tablename__ = "export_artifacts"
    credit_review_version_id = Column(UUID(as_uuid=True), ForeignKey("credit_review_versions.id"), nullable=False)
    type = Column(String(20), nullable=False)  # PDF, DOCX, XLSX, PPTX
    storage_url = Column(String(1000), nullable=True)
    credit_review_version = relationship("CreditReviewVersion", back_populates="export_artifacts")

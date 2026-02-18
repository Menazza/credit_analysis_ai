from sqlalchemy import Column, String, ForeignKey, Date, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import enum

from app.db.base_class import BaseModel
from app.db.session import Base


class EngagementType(str, enum.Enum):
    ANNUAL_REVIEW = "ANNUAL_REVIEW"
    NEW_FACILITY = "NEW_FACILITY"
    INCREASE = "INCREASE"
    MONITORING = "MONITORING"


class ReviewStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    NEEDS_MAPPING = "NEEDS_MAPPING"
    NEEDS_UNITS = "NEEDS_UNITS"
    FAILED_VALIDATION = "FAILED_VALIDATION"


class Company(Base, BaseModel):
    __tablename__ = "companies"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    reg_no = Column(String(100), nullable=True)
    country = Column(String(2), nullable=True)
    sector = Column(String(100), nullable=True)
    is_listed = Column(String(10), default="false")  # JSE / private
    ticker = Column(String(20), nullable=True)
    group_structure_json = Column(JSONB, default=dict)
    engagements = relationship("Engagement", back_populates="company")
    documents = relationship("Document", back_populates="company")
    facilities = relationship("Facility", back_populates="company")
    security_items = relationship("SecurityItem", back_populates="company")
    normalized_facts = relationship("NormalizedFact", back_populates="company")


class Engagement(Base, BaseModel):
    __tablename__ = "engagements"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    # Human-friendly engagement name, e.g. "FY25 Annual Review"
    name = Column(String(255), nullable=True)
    type = Column(String(50), nullable=False)  # EngagementType
    status = Column(String(50), default="ACTIVE")
    company = relationship("Company", back_populates="engagements")
    credit_reviews = relationship("CreditReview", back_populates="engagement")
    documents = relationship("Document", back_populates="engagement")


class CreditReview(Base, BaseModel):
    __tablename__ = "credit_reviews"
    engagement_id = Column(UUID(as_uuid=True), ForeignKey("engagements.id"), nullable=False)
    review_period_end = Column(Date, nullable=True)
    base_currency = Column(String(3), default="ZAR")
    status = Column(String(50), default=ReviewStatus.DRAFT.value)
    engagement = relationship("Engagement", back_populates="credit_reviews")
    versions = relationship("CreditReviewVersion", back_populates="credit_review")


class CreditReviewVersion(Base, BaseModel):
    __tablename__ = "credit_review_versions"
    credit_review_id = Column(UUID(as_uuid=True), ForeignKey("credit_reviews.id"), nullable=False)
    version_no = Column(String(20), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    locked_at = Column(Date, nullable=True)
    lock_reason = Column(String(500), nullable=True)
    credit_review = relationship("CreditReview", back_populates="versions")
    metric_facts = relationship("MetricFact", back_populates="credit_review_version")
    rating_results = relationship("RatingResult", back_populates="credit_review_version")
    commentary_blocks = relationship("CommentaryBlock", back_populates="credit_review_version")
    export_artifacts = relationship("ExportArtifact", back_populates="credit_review_version")

from sqlalchemy import Column, String, ForeignKey, Date, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base_class import BaseModel
from app.db.session import Base


class Facility(Base, BaseModel):
    __tablename__ = "facilities"
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    lender = Column(String(255), nullable=True)
    facility_type = Column(String(100), nullable=True)
    limit = Column(Float, nullable=True)
    utilisation = Column(Float, nullable=True)
    currency = Column(String(3), nullable=True)
    pricing_json = Column(JSONB, default=dict)
    maturity_date = Column(Date, nullable=True)
    amort_profile_json = Column(JSONB, default=dict)
    status = Column(String(50), default="ACTIVE")
    company = relationship("Company", back_populates="facilities")
    covenants = relationship("Covenant", back_populates="facility")


class SecurityItem(Base, BaseModel):
    __tablename__ = "security_items"
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    security_type = Column(String(100), nullable=True)
    description = Column(String(1000), nullable=True)
    value_estimate = Column(Float, nullable=True)
    ranking = Column(String(50), nullable=True)
    evidence_json = Column(JSONB, default=dict)
    company = relationship("Company", back_populates="security_items")


class Covenant(Base, BaseModel):
    __tablename__ = "covenants"
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)
    name = Column(String(200), nullable=False)
    definition_json = Column(JSONB, default=dict)
    threshold_json = Column(JSONB, default=dict)  # min/max, testing frequency
    testing_frequency = Column(String(50), nullable=True)
    notes = Column(String(500), nullable=True)
    facility = relationship("Facility", back_populates="covenants")
    tests = relationship("CovenantTest", back_populates="covenant")


class CovenantTest(Base, BaseModel):
    __tablename__ = "covenant_tests"
    covenant_id = Column(UUID(as_uuid=True), ForeignKey("covenants.id"), nullable=False)
    test_date = Column(Date, nullable=False)
    actual_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    headroom = Column(Float, nullable=True)
    status = Column(String(20), nullable=True)  # PASS, BREACH, WARN
    evidence_json = Column(JSONB, default=dict)
    covenant = relationship("Covenant", back_populates="tests")

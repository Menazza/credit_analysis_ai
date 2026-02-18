from sqlalchemy import Column, String, ForeignKey, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import enum

from app.db.base_class import BaseModel
from app.db.session import Base


class RoleName(str, enum.Enum):
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class Tenant(Base, BaseModel):
    __tablename__ = "tenants"
    name = Column(String(255), nullable=False)
    settings_json = Column(JSONB, default=dict)


class User(Base, BaseModel):
    __tablename__ = "users"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)
    status = Column(String(50), default="ACTIVE")
    tenant = relationship("Tenant", backref="users")


class Role(Base, BaseModel):
    __tablename__ = "roles"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name = Column(String(50), nullable=False)
    tenant = relationship("Tenant", backref="roles")


class UserRole(Base, BaseModel):
    __tablename__ = "user_roles"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    user = relationship("User", backref="user_roles")
    role = relationship("Role", backref="user_roles")


class Portfolio(Base, BaseModel):
    __tablename__ = "portfolios"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    tenant = relationship("Tenant", backref="portfolios")
    companies = relationship("PortfolioCompany", back_populates="portfolio")


class PortfolioCompany(Base, BaseModel):
    __tablename__ = "portfolio_companies"
    portfolio_id = Column(UUID(as_uuid=True), ForeignKey("portfolios.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    portfolio = relationship("Portfolio", back_populates="companies")

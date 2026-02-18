from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base_class import BaseModel
from app.db.session import Base


class AuditLog(Base, BaseModel):
    __tablename__ = "audit_log"
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    diff_json = Column(JSONB, default=dict)

"""SQLAlchemy ORM models for VendorFAIR."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    vendors = relationship("Vendor", back_populates="tenant")


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    website = Column(String(512), default="")
    category = Column(String(64), default="SaaS")  # SaaS | IaaS | Professional Services | Hardware
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    contract_status = Column(String(32), default="in evaluation")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="vendors")
    assessments = relationship("VendorAssessment", back_populates="vendor")


class VendorAssessment(Base):
    __tablename__ = "vendor_assessments"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    assessor = Column(String(255), default="")
    status = Column(String(16), default="draft")  # draft | complete | approved

    # Intake fields (comma-separated lists stored as text)
    data_types_accessed = Column(Text, default="")
    integration_depth = Column(String(64), default="")
    regulatory_context = Column(Text, default="")

    # Research fields
    research_json = Column(Text, default="")  # full AI output as JSON string
    research_confidence = Column(String(16), default="")
    certifications_found = Column(Text, default="")
    breach_history_summary = Column(Text, default="")
    incident_severity = Column(String(16), default="")
    public_trust_posture = Column(String(16), default="")

    # FAIR inputs (PERT min / most-likely / max)
    tef_min = Column(Float, default=0.1)
    tef_ml = Column(Float, default=0.5)
    tef_max = Column(Float, default=2.0)
    tc_min = Column(Float, default=0.3)
    tc_ml = Column(Float, default=0.6)
    tc_max = Column(Float, default=0.85)
    cs_min = Column(Float, default=0.4)
    cs_ml = Column(Float, default=0.65)
    cs_max = Column(Float, default=0.9)
    plm_min = Column(Float, default=10_000.0)
    plm_ml = Column(Float, default=75_000.0)
    plm_max = Column(Float, default=500_000.0)
    slm_min = Column(Float, default=5_000.0)
    slm_ml = Column(Float, default=25_000.0)
    slm_max = Column(Float, default=150_000.0)

    # FAIR outputs
    ale_p10 = Column(Float)
    ale_p50 = Column(Float)
    ale_p90 = Column(Float)
    risk_tier = Column(String(16))

    # Meta
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_by = Column(String(255))
    approved_at = Column(DateTime)

    vendor = relationship("Vendor", back_populates="assessments")
    history = relationship("AssessmentHistory", back_populates="assessment")


class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(128), nullable=False, unique=True)
    value = Column(Text, default="")  # Fernet ciphertext when is_encrypted
    is_encrypted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), nullable=False, unique=True)
    full_name = Column(String(255), default="")
    email = Column(String(255), default="")
    role = Column(String(32), nullable=False, default="viewer")  # admin | risk_manager | assessor | viewer
    password_hash = Column(String(512), nullable=False)  # pbkdf2_sha256$iterations$salt$hash
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    username = Column(String(64), nullable=False, index=True)
    role = Column(String(32), default="")
    action = Column(String(64), nullable=False, index=True)
    entity_type = Column(String(64), default="")
    entity_id = Column(Integer)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    details = Column(Text, default="")  # free text or JSON string


class AssessmentHistory(Base):
    __tablename__ = "assessment_history"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("vendor_assessments.id"), nullable=False)
    snapshot_date = Column(DateTime, default=datetime.utcnow)
    ale_p50 = Column(Float)
    risk_tier = Column(String(16))

    assessment = relationship("VendorAssessment", back_populates="history")

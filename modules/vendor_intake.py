"""Vendor intake form persistence logic."""
from datetime import datetime

from database.db import session_scope
from database.models import AssessmentHistory, Tenant, Vendor, VendorAssessment

VENDOR_CATEGORIES = ["SaaS", "IaaS", "Professional Services", "Hardware"]
DATA_TYPES = ["PII", "PHI", "financial", "IP", "credentials", "none"]
INTEGRATION_DEPTHS = ["API/SSO", "network-level", "data processing", "read-only", "none"]
REGULATORY_OPTIONS = ["PIPEDA", "SOC2", "PCI-DSS", "HIPAA"]
CONTRACT_STATUSES = ["in evaluation", "active", "renewal", "offboarding"]


def list_tenants():
    with session_scope() as session:
        return session.query(Tenant).order_by(Tenant.name).all()


def create_tenant(name: str, description: str = ""):
    with session_scope() as session:
        tenant = Tenant(name=name.strip(), description=description)
        session.add(tenant)
        session.flush()
        return tenant.id


def save_vendor_intake(
    tenant_id: int,
    name: str,
    website: str,
    category: str,
    contract_status: str,
    data_types: list[str],
    integration_depth: str,
    regulatory_context: list[str],
    assessor: str = "",
) -> tuple[int, int]:
    """Create vendor + draft assessment. Returns (vendor_id, assessment_id)."""
    with session_scope() as session:
        vendor = Vendor(
            name=name.strip(),
            website=website.strip(),
            category=category,
            tenant_id=tenant_id,
            contract_status=contract_status,
        )
        session.add(vendor)
        session.flush()
        assessment = VendorAssessment(
            vendor_id=vendor.id,
            assessor=assessor,
            status="draft",
            data_types_accessed=", ".join(data_types),
            integration_depth=integration_depth,
            regulatory_context=", ".join(regulatory_context),
        )
        session.add(assessment)
        session.flush()
        return vendor.id, assessment.id


def get_latest_assessment(vendor_id: int):
    """Return the most recent assessment for a vendor, or None."""
    with session_scope() as session:
        a = (
            session.query(VendorAssessment)
            .filter(VendorAssessment.vendor_id == vendor_id)
            .order_by(VendorAssessment.created_at.desc(), VendorAssessment.id.desc())
            .first()
        )
        if a is not None:
            _ = a.vendor, a.vendor.tenant  # eager-load before session closes
        return a


# FAIR input columns copied from the previous assessment on re-evaluation
_FAIR_INPUT_FIELDS = [
    f"{prefix}_{suffix}"
    for prefix in ("tef", "tc", "cs", "plm", "slm")
    for suffix in ("min", "ml", "max")
]


def create_reassessment(vendor_id: int, assessor: str = "") -> int:
    """Start a re-evaluation: new draft assessment seeded from the latest one.

    Intake fields and FAIR inputs carry over as a starting point; research
    fields and simulation outputs reset so the vendor is assessed fresh.
    Returns the new assessment id.
    """
    with session_scope() as session:
        previous = (
            session.query(VendorAssessment)
            .filter(VendorAssessment.vendor_id == vendor_id)
            .order_by(VendorAssessment.created_at.desc(), VendorAssessment.id.desc())
            .first()
        )
        if previous is None:
            raise ValueError(f"Vendor {vendor_id} has no assessment to re-evaluate.")
        assessment = VendorAssessment(
            vendor_id=vendor_id,
            assessor=assessor,
            status="draft",
            data_types_accessed=previous.data_types_accessed,
            integration_depth=previous.integration_depth,
            regulatory_context=previous.regulatory_context,
            **{field: getattr(previous, field) for field in _FAIR_INPUT_FIELDS},
        )
        session.add(assessment)
        session.flush()
        return assessment.id


def update_assessment_research(assessment_id: int, research: dict, research_json: str):
    """Persist AI research results onto the assessment."""
    fair = research.get("recommended_fair_inputs", {})
    with session_scope() as session:
        a = session.get(VendorAssessment, assessment_id)
        a.research_json = research_json
        a.research_confidence = research.get("research_confidence", "")
        a.certifications_found = ", ".join(map(str, research.get("certifications_found") or []))
        a.breach_history_summary = "; ".join(map(str, research.get("breach_history") or []))
        a.incident_severity = research.get("incident_severity", "")
        a.public_trust_posture = research.get("public_trust_posture", "")
        for key, value in fair.items():
            if hasattr(a, key):
                setattr(a, key, float(value))


def update_assessment_fair(assessment_id: int, fair_inputs: dict, percentiles: dict, risk_tier: str):
    """Persist FAIR inputs + simulation outputs and snapshot to history."""
    with session_scope() as session:
        a = session.get(VendorAssessment, assessment_id)
        for key, value in fair_inputs.items():
            if hasattr(a, key):
                setattr(a, key, float(value))
        a.ale_p10 = percentiles["p10"]
        a.ale_p50 = percentiles["p50"]
        a.ale_p90 = percentiles["p90"]
        a.risk_tier = risk_tier
        a.status = "complete"
        session.add(
            AssessmentHistory(
                vendor_id=a.vendor_id,
                assessment_id=a.id,
                snapshot_date=datetime.utcnow(),
                ale_p50=percentiles["p50"],
                risk_tier=risk_tier,
            )
        )


def reset_data(tenant_id: int | None = None) -> dict:
    """Delete vendors, assessments, and history — for one tenant or all.

    Tenants, users, settings, and the audit log are preserved.
    Returns deletion counts.
    """
    with session_scope() as session:
        vendor_query = session.query(Vendor.id)
        if tenant_id is not None:
            vendor_query = vendor_query.filter(Vendor.tenant_id == tenant_id)
        vendor_ids = [row[0] for row in vendor_query.all()]
        if not vendor_ids:
            return {"vendors": 0, "assessments": 0, "history": 0}
        history = (
            session.query(AssessmentHistory)
            .filter(AssessmentHistory.vendor_id.in_(vendor_ids))
            .delete(synchronize_session=False)
        )
        assessments = (
            session.query(VendorAssessment)
            .filter(VendorAssessment.vendor_id.in_(vendor_ids))
            .delete(synchronize_session=False)
        )
        vendors = (
            session.query(Vendor)
            .filter(Vendor.id.in_(vendor_ids))
            .delete(synchronize_session=False)
        )
        return {"vendors": vendors, "assessments": assessments, "history": history}


def get_assessment(assessment_id: int):
    with session_scope() as session:
        a = session.get(VendorAssessment, assessment_id)
        if a is not None:
            _ = a.vendor, a.vendor.tenant  # eager-load before session closes
        return a

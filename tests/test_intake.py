"""Database intake tests against a temporary SQLite file."""
import pytest

import database.db as db
from database.models import Tenant, Vendor, VendorAssessment
from modules import vendor_intake


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Point the module-level engine at a fresh temp database for each test."""
    db._engine = None
    db._SessionLocal = None
    db.init_db(str(tmp_path / "test.db"))
    yield
    db._engine = None
    db._SessionLocal = None


def test_default_tenant_seeded():
    tenants = vendor_intake.list_tenants()
    assert len(tenants) == 1
    assert tenants[0].name == "Default Tenant"


def test_intake_saves_vendor_and_assessment():
    tenant = vendor_intake.list_tenants()[0]
    vendor_id, assessment_id = vendor_intake.save_vendor_intake(
        tenant_id=tenant.id,
        name="Acme SaaS",
        website="https://acme.example",
        category="SaaS",
        contract_status="in evaluation",
        data_types=["PII", "financial"],
        integration_depth="API/SSO",
        regulatory_context=["SOC2", "PIPEDA"],
        assessor="Tester",
    )
    with db.session_scope() as session:
        vendor = session.get(Vendor, vendor_id)
        assessment = session.get(VendorAssessment, assessment_id)
        assert vendor.name == "Acme SaaS"
        assert vendor.tenant_id == tenant.id
        assert assessment.data_types_accessed == "PII, financial"
        assert assessment.regulatory_context == "SOC2, PIPEDA"
        assert assessment.status == "draft"


def test_fair_update_writes_outputs_and_history():
    tenant = vendor_intake.list_tenants()[0]
    _, assessment_id = vendor_intake.save_vendor_intake(
        tenant_id=tenant.id, name="V", website="", category="SaaS",
        contract_status="active", data_types=[], integration_depth="none",
        regulatory_context=[],
    )
    vendor_intake.update_assessment_fair(
        assessment_id,
        fair_inputs={"tef_ml": 0.7},
        percentiles={"p10": 100.0, "p50": 5_000.0, "p90": 40_000.0},
        risk_tier="Low",
    )
    a = vendor_intake.get_assessment(assessment_id)
    assert a.ale_p50 == 5_000.0
    assert a.risk_tier == "Low"
    assert a.status == "complete"
    assert a.tef_ml == 0.7
    with db.session_scope() as session:
        from database.models import AssessmentHistory
        history = session.query(AssessmentHistory).filter_by(assessment_id=assessment_id).all()
        assert len(history) == 1
        assert history[0].risk_tier == "Low"

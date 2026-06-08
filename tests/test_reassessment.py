"""Vendor re-evaluation tests against a temporary SQLite file."""
import pytest

import database.db as db
from database.models import Vendor, VendorAssessment
from modules import risk_register, vendor_intake


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Point the module-level engine at a fresh temp database for each test."""
    db._engine = None
    db._SessionLocal = None
    db.init_db(str(tmp_path / "test.db"))
    yield
    db._engine = None
    db._SessionLocal = None


def _seed_completed_assessment():
    tenant = vendor_intake.list_tenants()[0]
    vendor_id, assessment_id = vendor_intake.save_vendor_intake(
        tenant_id=tenant.id,
        name="Acme SaaS",
        website="https://acme.example",
        category="SaaS",
        contract_status="active",
        data_types=["PII", "financial"],
        integration_depth="API/SSO",
        regulatory_context=["SOC2"],
        assessor="Original Assessor",
    )
    fair_inputs = {"tef_min": 0.2, "tef_ml": 0.7, "tef_max": 3.0, "plm_ml": 90_000.0}
    vendor_intake.update_assessment_fair(
        assessment_id, fair_inputs,
        {"p10": 1000.0, "p50": 5000.0, "p90": 20000.0}, "Moderate",
    )
    return vendor_id, assessment_id


def test_reassessment_copies_intake_and_fair_inputs():
    vendor_id, original_id = _seed_completed_assessment()
    new_id = vendor_intake.create_reassessment(vendor_id, assessor="New Assessor")
    assert new_id != original_id

    new = vendor_intake.get_assessment(new_id)
    original = vendor_intake.get_assessment(original_id)
    assert new.vendor_id == vendor_id
    assert new.status == "draft"
    assert new.assessor == "New Assessor"
    # Intake fields carried over
    assert new.data_types_accessed == original.data_types_accessed
    assert new.integration_depth == original.integration_depth
    assert new.regulatory_context == original.regulatory_context
    # FAIR inputs carried over (including the customized ones)
    assert new.tef_ml == 0.7
    assert new.plm_ml == 90_000.0
    # Research fields and outputs reset
    assert new.research_json == ""
    assert new.certifications_found == ""
    assert new.ale_p50 is None
    assert new.risk_tier is None
    # Original untouched
    assert original.status == "complete"
    assert original.risk_tier == "Moderate"


def test_reassessment_seeds_from_latest_not_first():
    vendor_id, _ = _seed_completed_assessment()
    second_id = vendor_intake.create_reassessment(vendor_id)
    vendor_intake.update_assessment_fair(
        second_id, {"tef_ml": 1.5},
        {"p10": 2000.0, "p50": 9000.0, "p90": 40000.0}, "High",
    )
    third_id = vendor_intake.create_reassessment(vendor_id)
    assert vendor_intake.get_assessment(third_id).tef_ml == 1.5


def test_reassessment_requires_existing_assessment():
    tenant = vendor_intake.list_tenants()[0]
    with db.session_scope() as session:
        vendor = Vendor(name="No Assessment Inc", tenant_id=tenant.id)
        session.add(vendor)
        session.flush()
        vendor_id = vendor.id
    with pytest.raises(ValueError, match="no assessment"):
        vendor_intake.create_reassessment(vendor_id)


def test_get_latest_assessment():
    vendor_id, original_id = _seed_completed_assessment()
    assert vendor_intake.get_latest_assessment(vendor_id).id == original_id
    new_id = vendor_intake.create_reassessment(vendor_id)
    assert vendor_intake.get_latest_assessment(vendor_id).id == new_id


def test_register_latest_only_filter():
    vendor_id, original_id = _seed_completed_assessment()
    new_id = vendor_intake.create_reassessment(vendor_id)

    df_all = risk_register.load_register(latest_only=False)
    assert len(df_all) == 2

    df_latest = risk_register.load_register(latest_only=True)
    assert len(df_latest) == 1
    assert df_latest.iloc[0]["Assessment ID"] == new_id


def test_trend_accumulates_across_reassessments():
    vendor_id, _ = _seed_completed_assessment()
    new_id = vendor_intake.create_reassessment(vendor_id)
    vendor_intake.update_assessment_fair(
        new_id, {}, {"p10": 2000.0, "p50": 9000.0, "p90": 40000.0}, "High",
    )
    trend = risk_register.load_trend(vendor_id)
    assert len(trend) == 2
    assert list(trend["Risk Tier"]) == ["Moderate", "High"]

"""Encrypted settings store and reset-data tests against a temporary SQLite file."""
import os
import stat

import pytest

import database.db as db
from database.models import AppSetting
from modules import settings_store, vendor_intake


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Fresh temp database + temp encryption key file for each test."""
    monkeypatch.setattr(settings_store, "_KEY_FILE", tmp_path / ".vendorfair.key")
    monkeypatch.setattr(settings_store, "_fernet", None)
    db._engine = None
    db._SessionLocal = None
    db.init_db(str(tmp_path / "test.db"))
    yield
    db._engine = None
    db._SessionLocal = None


# ---------------------------------------------------------------- encryption
def test_secret_roundtrip_and_encrypted_at_rest():
    settings_store.set_api_key("anthropic", "sk-ant-secret-12345")
    assert settings_store.get_api_key("anthropic") == "sk-ant-secret-12345"
    # The raw DB value must not contain the plaintext key
    with db.session_scope() as session:
        row = session.query(AppSetting).filter(AppSetting.key == "api_key_anthropic").one()
        assert row.is_encrypted
        assert "sk-ant-secret-12345" not in row.value


def test_key_file_created_with_0600():
    settings_store.set_api_key("openai", "sk-test-99999999")
    mode = stat.S_IMODE(os.stat(settings_store._KEY_FILE).st_mode)
    assert mode == 0o600


def test_api_key_hint_is_masked():
    settings_store.set_api_key("gemini", "AIzaSyExample1234")
    hint = settings_store.api_key_hint("gemini")
    assert "1234" in hint
    assert "AIzaSyExample" not in hint


def test_clear_api_key():
    settings_store.set_api_key("openai", "sk-test-99999999")
    settings_store.clear_api_key("openai")
    assert settings_store.get_setting("api_key_openai") is None


def test_env_fallback_when_no_stored_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert settings_store.get_api_key("openai") == "sk-from-env"
    assert "env" in settings_store.api_key_hint("openai")
    # Stored key takes precedence over env
    settings_store.set_api_key("openai", "sk-stored")
    assert settings_store.get_api_key("openai") == "sk-stored"


def test_unreadable_secret_after_key_loss(tmp_path, monkeypatch):
    settings_store.set_api_key("anthropic", "sk-ant-secret-12345")
    # Simulate a replaced encryption key
    settings_store._KEY_FILE.unlink()
    monkeypatch.setattr(settings_store, "_fernet", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert settings_store.get_api_key("anthropic") == ""


# ---------------------------------------------------------------- provider config
def test_provider_defaults_and_roundtrip():
    assert settings_store.get_ai_provider() == "anthropic"
    settings_store.set_ai_provider("gemini")
    assert settings_store.get_ai_provider() == "gemini"
    assert settings_store.get_ai_model("gemini") == settings_store.DEFAULT_MODELS["gemini"]
    settings_store.set_ai_model("gemini", "gemini-2.5-pro")
    assert settings_store.get_ai_model("gemini") == "gemini-2.5-pro"


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        settings_store.set_ai_provider("llama")
    with pytest.raises(ValueError):
        settings_store.get_api_key("llama")


# ---------------------------------------------------------------- reset data
def _seed(tenant_id, name):
    vendor_id, assessment_id = vendor_intake.save_vendor_intake(
        tenant_id=tenant_id, name=name, website="", category="SaaS",
        contract_status="active", data_types=["PII"], integration_depth="API/SSO",
        regulatory_context=["SOC2"], assessor="t",
    )
    vendor_intake.update_assessment_fair(
        assessment_id, {}, {"p10": 1.0, "p50": 2.0, "p90": 3.0}, "Low",
    )
    return vendor_id


def test_reset_data_single_tenant():
    t1 = vendor_intake.list_tenants()[0].id
    t2 = vendor_intake.create_tenant("Other Tenant")
    _seed(t1, "Vendor A")
    _seed(t2, "Vendor B")

    counts = vendor_intake.reset_data(tenant_id=t1)
    assert counts == {"vendors": 1, "assessments": 1, "history": 1}
    # Other tenant untouched
    assert len(risk_vendors(t2)) == 1
    assert len(risk_vendors(t1)) == 0


def test_reset_data_all_tenants():
    t1 = vendor_intake.list_tenants()[0].id
    t2 = vendor_intake.create_tenant("Other Tenant")
    _seed(t1, "Vendor A")
    _seed(t2, "Vendor B")

    counts = vendor_intake.reset_data()
    assert counts == {"vendors": 2, "assessments": 2, "history": 2}
    # Tenants survive a reset
    assert len(vendor_intake.list_tenants()) == 2


def test_reset_data_empty_is_noop():
    assert vendor_intake.reset_data() == {"vendors": 0, "assessments": 0, "history": 0}


def risk_vendors(tenant_id):
    from modules import risk_register
    return risk_register.list_vendors(tenant_id)

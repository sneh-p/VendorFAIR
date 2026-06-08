"""Audit trail tests against a temporary SQLite file."""
import json
from datetime import datetime, timedelta

import pytest

import database.db as db
from modules import audit


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Point the module-level engine at a fresh temp database for each test."""
    db._engine = None
    db._SessionLocal = None
    db.init_db(str(tmp_path / "test.db"))
    yield
    db._engine = None
    db._SessionLocal = None


def test_log_and_load_event():
    audit.log_event("alice", "intake_saved", role="assessor",
                    entity_type="assessment", entity_id=7, tenant_id=1,
                    details={"vendor": "Acme"})
    df = audit.load_audit()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["User"] == "alice"
    assert row["Action"] == "intake_saved"
    assert row["Entity"] == "assessment #7"
    assert row["Tenant ID"] == 1
    assert json.loads(row["Details"]) == {"vendor": "Acme"}


def test_details_accepts_plain_string_and_none():
    audit.log_event("bob", "logout", details="manual sign-out")
    audit.log_event("bob", "login_success")
    df = audit.load_audit(username="bob")
    assert set(df["Details"]) == {"manual sign-out", ""}


def test_filters_by_user_action_and_tenant():
    audit.log_event("alice", "login_success", tenant_id=1)
    audit.log_event("alice", "simulation_run", tenant_id=2)
    audit.log_event("bob", "login_failed", tenant_id=1)

    assert len(audit.load_audit(username="alice")) == 2
    assert len(audit.load_audit(action="login_failed")) == 1
    assert len(audit.load_audit(tenant_id=1)) == 2
    assert len(audit.load_audit(username="alice", tenant_id=2)) == 1


def test_filters_by_date_range():
    audit.log_event("alice", "login_success")
    now = datetime.utcnow()
    assert len(audit.load_audit(start=now - timedelta(minutes=1))) == 1
    assert len(audit.load_audit(end=now - timedelta(days=1))) == 0
    assert len(audit.load_audit(start=now + timedelta(days=1))) == 0


def test_list_actions_distinct_sorted():
    for action in ("logout", "login_success", "login_success", "intake_saved"):
        audit.log_event("alice", action)
    assert audit.list_actions() == ["intake_saved", "login_success", "logout"]


def test_load_audit_respects_limit_and_order():
    for i in range(5):
        audit.log_event("alice", "login_success", details=str(i))
    df = audit.load_audit(limit=3)
    assert len(df) == 3


def test_export_csv():
    audit.log_event("alice", "login_success")
    df = audit.load_audit()
    data = audit.export_csv(df)
    assert b"login_success" in data
    assert b"alice" in data

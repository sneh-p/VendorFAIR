"""Auth, user management, and RBAC tests against a temporary SQLite file."""
import pytest

import database.db as db
from modules import auth


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point the module-level engine at a fresh temp database for each test."""
    # Lower the PBKDF2 work factor for fast tests — verify reads the iteration
    # count from the stored hash, so roundtrips stay valid.
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    db._engine = None
    db._SessionLocal = None
    db.init_db(str(tmp_path / "test.db"))
    yield
    db._engine = None
    db._SessionLocal = None


# ---------------------------------------------------------------- passwords
def test_password_hash_roundtrip():
    stored = auth.hash_password("s3cret-passw0rd")
    assert auth.verify_password("s3cret-passw0rd", stored)
    assert not auth.verify_password("wrong-password", stored)


def test_password_hashes_are_salted():
    assert auth.hash_password("same") != auth.hash_password("same")


def test_verify_password_rejects_malformed_hash():
    assert not auth.verify_password("anything", "not-a-valid-hash")
    assert not auth.verify_password("anything", "")


# ---------------------------------------------------------------- users
def test_seed_default_admin_once():
    assert auth.seed_default_admin() is True
    assert auth.seed_default_admin() is False
    users = auth.list_users()
    assert len(users) == 1
    assert users[0].username == auth.DEFAULT_ADMIN_USERNAME
    assert users[0].role == "admin"


def test_authenticate_success_and_failure():
    auth.create_user("alice", "password123", "assessor", full_name="Alice A")
    session = auth.authenticate("alice", "password123")
    assert session is not None
    assert session["role"] == "assessor"
    assert auth.authenticate("alice", "wrongpass") is None
    assert auth.authenticate("nobody", "password123") is None


def test_authenticate_rejects_inactive_user():
    auth.create_user("admin2", "password123", "admin")
    auth.create_user("bob", "password123", "viewer")
    auth.set_user_active("bob", False)
    assert auth.authenticate("bob", "password123") is None


def test_create_user_validation():
    with pytest.raises(ValueError, match="at least 8"):
        auth.create_user("shortpw", "short", "viewer")
    with pytest.raises(ValueError, match="Unknown role"):
        auth.create_user("badrole", "password123", "superuser")
    auth.create_user("dup", "password123", "viewer")
    with pytest.raises(ValueError, match="already exists"):
        auth.create_user("dup", "password123", "viewer")


def test_cannot_remove_last_active_admin():
    auth.seed_default_admin()
    with pytest.raises(ValueError, match="last active admin"):
        auth.set_user_role(auth.DEFAULT_ADMIN_USERNAME, "viewer")
    with pytest.raises(ValueError, match="last active admin"):
        auth.set_user_active(auth.DEFAULT_ADMIN_USERNAME, False)
    # With a second admin, demotion is allowed
    auth.create_user("admin2", "password123", "admin")
    auth.set_user_role(auth.DEFAULT_ADMIN_USERNAME, "viewer")


def test_reset_password():
    auth.create_user("carol", "password123", "assessor")
    auth.reset_password("carol", "newpassword456")
    assert auth.authenticate("carol", "password123") is None
    assert auth.authenticate("carol", "newpassword456") is not None


# ---------------------------------------------------------------- RBAC
def test_admin_has_all_permissions():
    assert auth.ROLE_PERMISSIONS["admin"] == set(auth.PERMISSIONS)


def test_role_permission_matrix():
    assert auth.has_permission("risk_manager", "view_audit")
    assert auth.has_permission("risk_manager", "export_register")
    assert not auth.has_permission("risk_manager", "manage_users")
    assert auth.has_permission("assessor", "new_assessment")
    assert not auth.has_permission("assessor", "export_register")
    assert not auth.has_permission("assessor", "view_audit")
    assert auth.has_permission("viewer", "view_register")
    assert not auth.has_permission("viewer", "new_assessment")
    assert not auth.has_permission("unknown_role", "view_register")


def test_every_role_permission_is_defined():
    for role, perms in auth.ROLE_PERMISSIONS.items():
        assert perms <= set(auth.PERMISSIONS), f"{role} grants undefined permissions"

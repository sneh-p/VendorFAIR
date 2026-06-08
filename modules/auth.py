"""Authentication, user management, and role-based access control."""
import hashlib
import hmac
import secrets
from datetime import datetime

from database.db import session_scope
from database.models import User

PBKDF2_ITERATIONS = 200_000

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"

ROLE_DESCRIPTIONS = {
    "admin": "Full access — user management, settings, audit log, and all assessment features",
    "risk_manager": "Run assessments, export the register, and review the audit log",
    "assessor": "Create and run vendor assessments and generate reports",
    "viewer": "Read-only access to the risk register and assessment history",
}
ROLES = list(ROLE_DESCRIPTIONS)

PERMISSIONS = {
    "new_assessment": "Create vendor intakes and edit FAIR inputs",
    "run_research": "Run AI auto-research on vendors",
    "run_simulation": "Run Monte Carlo simulations",
    "generate_reports": "Generate DOCX/PDF reports",
    "view_register": "View the vendor risk register",
    "export_register": "Export the risk register (CSV/XLSX)",
    "view_history": "View assessment history and risk trends",
    "view_audit": "View the audit log",
    "manage_users": "Create and manage user accounts",
    "manage_settings": "Manage tenants, logo, and app settings",
}

ROLE_PERMISSIONS = {
    "admin": set(PERMISSIONS),
    "risk_manager": {
        "new_assessment", "run_research", "run_simulation", "generate_reports",
        "view_register", "export_register", "view_history", "view_audit",
    },
    "assessor": {
        "new_assessment", "run_research", "run_simulation", "generate_reports",
        "view_register", "view_history",
    },
    "viewer": {"view_register", "view_history"},
}


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------- permissions
def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


# ---------------------------------------------------------------- users
def authenticate(username: str, password: str) -> dict | None:
    """Return a session dict for valid, active credentials; otherwise None."""
    with session_scope() as session:
        user = (
            session.query(User)
            .filter(User.username == username, User.is_active.is_(True))
            .first()
        )
        if user is None or not verify_password(password, user.password_hash):
            return None
        user.last_login = datetime.utcnow()
        return {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
        }


def create_user(username: str, password: str, role: str,
                full_name: str = "", email: str = "") -> int:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    if not username.strip():
        raise ValueError("Username is required.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    with session_scope() as session:
        if session.query(User).filter(User.username == username).first():
            raise ValueError(f"Username '{username}' already exists.")
        user = User(
            username=username.strip(), full_name=full_name, email=email,
            role=role, password_hash=hash_password(password),
        )
        session.add(user)
        session.flush()
        return user.id


def list_users() -> list[User]:
    with session_scope() as session:
        return session.query(User).order_by(User.username).all()


def set_user_role(username: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    with session_scope() as session:
        user = _get_user_or_raise(session, username)
        if user.role == "admin" and role != "admin":
            _ensure_other_active_admin(session, username)
        user.role = role


def set_user_active(username: str, active: bool) -> None:
    with session_scope() as session:
        user = _get_user_or_raise(session, username)
        if user.role == "admin" and not active:
            _ensure_other_active_admin(session, username)
        user.is_active = active


def reset_password(username: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    with session_scope() as session:
        user = _get_user_or_raise(session, username)
        user.password_hash = hash_password(new_password)


def seed_default_admin() -> bool:
    """Create the default admin account if no users exist. Returns True if seeded."""
    with session_scope() as session:
        if session.query(User).count() > 0:
            return False
        session.add(User(
            username=DEFAULT_ADMIN_USERNAME,
            full_name="Default Administrator",
            role="admin",
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        ))
        return True


def _get_user_or_raise(session, username: str) -> User:
    user = session.query(User).filter(User.username == username).first()
    if user is None:
        raise ValueError(f"No such user: {username}")
    return user


def _ensure_other_active_admin(session, username: str) -> None:
    others = (
        session.query(User)
        .filter(User.role == "admin", User.is_active.is_(True), User.username != username)
        .count()
    )
    if others == 0:
        raise ValueError("Cannot remove the last active admin.")

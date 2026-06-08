"""Audit trail — event logging and querying."""
import json
from datetime import datetime

import pandas as pd

from database.db import session_scope
from database.models import AuditLog


def log_event(username: str, action: str, *, role: str = "",
              entity_type: str = "", entity_id: int | None = None,
              tenant_id: int | None = None, details=None) -> None:
    """Record a single audit event. `details` may be a string or JSON-serializable."""
    if details is None:
        details_text = ""
    elif isinstance(details, str):
        details_text = details
    else:
        details_text = json.dumps(details, default=str)
    with session_scope() as session:
        session.add(AuditLog(
            username=username, role=role, action=action,
            entity_type=entity_type, entity_id=entity_id,
            tenant_id=tenant_id, details=details_text,
        ))


def list_actions() -> list[str]:
    with session_scope() as session:
        rows = session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
        return [r[0] for r in rows]


def load_audit(start: datetime | None = None, end: datetime | None = None,
               username: str | None = None, action: str | None = None,
               tenant_id: int | None = None, limit: int = 1000) -> pd.DataFrame:
    with session_scope() as session:
        query = session.query(AuditLog)
        if start is not None:
            query = query.filter(AuditLog.timestamp >= start)
        if end is not None:
            query = query.filter(AuditLog.timestamp <= end)
        if username:
            query = query.filter(AuditLog.username == username)
        if action:
            query = query.filter(AuditLog.action == action)
        if tenant_id is not None:
            query = query.filter(AuditLog.tenant_id == tenant_id)
        rows = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()

    return pd.DataFrame([{
        "Timestamp (UTC)": r.timestamp,
        "User": r.username,
        "Role": r.role,
        "Action": r.action,
        "Entity": f"{r.entity_type} #{r.entity_id}" if r.entity_type else "",
        "Tenant ID": r.tenant_id,
        "Details": r.details,
    } for r in rows])


def export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()

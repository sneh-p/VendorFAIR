"""Database initialization and session management."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from database.models import Base, Tenant

_engine = None
_SessionLocal = None


def get_engine(db_path: str | None = None):
    global _engine, _SessionLocal
    if _engine is None:
        path = db_path or config.DB_PATH
        _engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db(db_path: str | None = None):
    """Create all tables and seed a default tenant if none exist."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    with session_scope() as session:
        if session.query(Tenant).count() == 0:
            session.add(Tenant(name="Default Tenant", description="Default client tenant"))
    return engine


def get_session():
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    if _SessionLocal is None:
        get_engine()
        Base.metadata.create_all(_engine)
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

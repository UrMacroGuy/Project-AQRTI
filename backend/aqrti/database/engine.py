"""
AQRTI Database Engine
Manages SQLAlchemy engine, session factory, and schema initialization.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from aqrti.config.settings import get_settings
from aqrti.database.models import Base
from aqrti.utils.logger import db_logger


def _build_engine():
    settings = get_settings()
    engine = create_engine(
        settings.db_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    # Enable WAL mode for better concurrent read performance
    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


@contextmanager
def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    db_logger.info("Database initialized — all tables verified.")


def get_db_dependency():
    """FastAPI dependency that yields a DB session."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()

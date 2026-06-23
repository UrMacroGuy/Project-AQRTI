"""
Session helpers — backwards-compatible aliases used across the codebase.
"""
from __future__ import annotations
from contextlib import contextmanager
from aqrti.database.engine import get_session_factory, get_db


def SessionLocal():
    """Return a bare session (caller must close it manually)."""
    return get_session_factory()()


@contextmanager
def get_db_session():
    """Context manager that yields a session, commits on success, rolls back on error."""
    with get_db() as db:
        yield db

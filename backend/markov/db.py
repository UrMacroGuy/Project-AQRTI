"""
Markov module DB access — shares the physical aqrti.db file via the existing
aqrti.database.engine connection, but creates/queries only MarkovBase tables.

Never imports aqrti.database.models (the main schema). Read access to
DailyPrice/IndexData (existing OHLCV tables) goes through raw SQL against the
same engine, not through the main ORM models, to keep the import graph clean.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session, sessionmaker

from aqrti.database.engine import get_engine
from aqrti.utils.logger import get_logger

from markov.models import MarkovBase

log = get_logger("markov.db")

_SessionLocal = None


def init_markov_schema() -> None:
    """Create markov_* tables if they don't exist. Safe to call every boot."""
    try:
        engine = get_engine()
        MarkovBase.metadata.create_all(bind=engine, checkfirst=True)
        log.info("Markov schema ready (markov_* tables).")
    except Exception:
        log.exception("Markov schema init failed — module will stay inactive this run.")


def get_markov_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


@contextmanager
def get_markov_db() -> Generator[Session, None, None]:
    factory = get_markov_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

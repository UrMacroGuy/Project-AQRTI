"""
AQRTI Database Engine
Manages SQLAlchemy engine, session factory, and schema initialization.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from aqrti.config.settings import get_settings
from aqrti.database.models import Base
from aqrti.utils.logger import db_logger

# Import lazily inside init_db to avoid circular imports at module load time.
# (migrations.py itself has no model imports, but belt-and-suspenders.)


def _build_engine():
    settings = get_settings()
    engine = create_engine(
        settings.db_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # NORMAL is safe with WAL and much faster than FULL
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Checkpoint every 1000 pages (~4 MB, SQLite's own default) rather
        # than 50 (~200 KB). The aggressive 50-page setting meant a
        # checkpoint (which needs a brief exclusive lock) fired on nearly
        # every write, and with 3 concurrent writers now hitting this file
        # (main backend, the separate Markov process, and the 5-min
        # strategy-loop subprocess — see docs/RESEARCH_DRIVEN_REARCHITECTURE.md),
        # that checkpoint churn was a real contributor to the "database is
        # locked" errors observed in evolution_engine/markov writes even
        # with a 30s busy_timeout. WAL growing a few MB larger between
        # checkpoints is a trivial tradeoff against fewer lock collisions.
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        # Wait up to 30 seconds when locked instead of failing immediately
        cursor.execute("PRAGMA busy_timeout=30000")
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


def checkpoint_wal() -> None:
    """Force a full WAL checkpoint — flush all WAL writes into the main DB file."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception as exc:
        db_logger.warning("WAL checkpoint failed: %s", exc)


def init_db() -> None:
    """Create all tables if they don't exist. Skips if DB already has tables."""
    from aqrti.database.migrations import ensure_migrations_table, run_pending

    engine = get_engine()
    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        ).scalar()
    if existing and existing > 5:
        # DB already initialized — just ensure any new tables are added
        Base.metadata.create_all(bind=engine, checkfirst=True)
        db_logger.info("Database already initialized (%d tables found).", existing)
    else:
        Base.metadata.create_all(bind=engine)
        db_logger.info("Database initialized — all tables created.")

    # Run lightweight schema migrations (idempotent; safe to call every boot).
    ensure_migrations_table(engine)
    run_pending(engine)


def get_db_dependency():
    """FastAPI dependency that yields a DB session and commits on clean exit."""
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

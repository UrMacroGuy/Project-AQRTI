"""
AQRTI lightweight migration engine.

Uses raw sqlite3 (not SQLAlchemy ORM) so migrations can run before any model
is imported.  The engine only needs a SQLAlchemy Engine whose URL points at the
SQLite file — we extract the path from it.

Public API
----------
    ensure_migrations_table(engine)  – create schema_migrations if absent
    get_applied(engine)              – set[str] of applied migration_id values
    apply(engine, migration_id, description, fn)  – run fn(conn) if not applied
    run_pending(engine)              – scan scripts/migrations/*.py and apply all pending
"""

from __future__ import annotations

import importlib.util
import logging
import sqlite3
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    migration_id TEXT     UNIQUE NOT NULL,
    applied_at   DATETIME NOT NULL DEFAULT (datetime('now')),
    description  TEXT
);
"""

# __file__ = backend/aqrti/database/migrations.py
# .parent      → backend/aqrti/database/
# .parent      → backend/aqrti/
# .parent      → backend/
# / scripts/migrations → backend/scripts/migrations/
_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "scripts" / "migrations"


def _db_path(engine) -> str:
    """Extract the filesystem path to the SQLite database from a SQLAlchemy engine."""
    url = str(engine.url)
    # url looks like: sqlite:////abs/path/to/file.db  or  sqlite:///relative.db
    if url.startswith("sqlite:////"):
        return url[len("sqlite:///"):]   # absolute path (4 slashes → 3 remain)
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]   # relative path
    raise ValueError(f"Unsupported database URL for migrations: {url!r}")


def _connect(engine) -> sqlite3.Connection:
    path = _db_path(engine)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_migrations_table(engine) -> None:
    """Create the schema_migrations tracking table if it does not exist."""
    conn = _connect(engine)
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def get_applied(engine) -> set[str]:
    """Return the set of migration_id strings that have already been applied."""
    conn = _connect(engine)
    try:
        rows = conn.execute("SELECT migration_id FROM schema_migrations").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def apply(
    engine,
    migration_id: str,
    description: str,
    fn: Callable[[sqlite3.Connection], None],
) -> bool:
    """
    Apply a single migration if it has not been applied yet.

    Parameters
    ----------
    engine       : SQLAlchemy Engine (used only to locate the DB file)
    migration_id : unique string identifying this migration
    description  : human-readable description stored in schema_migrations
    fn           : callable(conn) that performs the DDL/DML inside a transaction

    Returns True if the migration was applied, False if it was already recorded.
    Raises on any error (transaction is rolled back; migration NOT recorded).
    """
    conn = _connect(engine)
    try:
        applied = {
            row[0]
            for row in conn.execute(
                "SELECT migration_id FROM schema_migrations WHERE migration_id = ?",
                (migration_id,),
            ).fetchall()
        }
        if migration_id in applied:
            return False

        # Run inside an explicit transaction
        conn.execute("BEGIN")
        try:
            fn(conn)
            conn.execute(
                "INSERT INTO schema_migrations (migration_id, description) VALUES (?, ?)",
                (migration_id, description),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        logger.info("Migration applied: %s — %s", migration_id, description)
        return True
    finally:
        conn.close()


def run_pending(engine) -> None:
    """
    Discover and run all pending migrations from scripts/migrations/*.py,
    sorted by filename.  Each file must define:

        MIGRATION_ID : str
        DESCRIPTION  : str
        def up(conn) : callable receiving a sqlite3.Connection
    """
    migrations_dir = _MIGRATIONS_DIR
    if not migrations_dir.is_dir():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    py_files = sorted(migrations_dir.glob("*.py"))
    if not py_files:
        logger.debug("No migration files found in %s", migrations_dir)
        return

    applied = get_applied(engine)

    for path in py_files:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            logger.warning("Could not load migration file: %s", path)
            continue

        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("Failed to import migration %s: %s", path.name, exc)
            raise

        migration_id = getattr(mod, "MIGRATION_ID", None)
        description = getattr(mod, "DESCRIPTION", "")
        up_fn = getattr(mod, "up", None)

        if migration_id is None:
            logger.warning("Migration file %s missing MIGRATION_ID — skipped", path.name)
            continue
        if up_fn is None:
            logger.warning("Migration file %s missing up() — skipped", path.name)
            continue

        if migration_id in applied:
            logger.debug("Migration already applied: %s", migration_id)
            continue

        apply(engine, migration_id, description, up_fn)

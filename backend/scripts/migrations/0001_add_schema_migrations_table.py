"""
Migration 0001 — Bootstrap

The schema_migrations table is created by ensure_migrations_table() before
run_pending() is ever called, so there is nothing for up() to do here.
This file exists to record the bootstrap event in the migrations log.
"""

MIGRATION_ID = "0001_add_schema_migrations_table"
DESCRIPTION = "Bootstrap: record of all applied migrations"


def up(conn):  # noqa: ARG001
    """Table already created by ensure_migrations_table(); nothing to do."""
    pass

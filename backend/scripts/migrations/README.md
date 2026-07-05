# AQRTI Migration Convention

Lightweight SQLite migrations — no Alembic, no ORM dependency.

## How it works

- `backend/aqrti/database/migrations.py` is the migration engine.
- On startup (`init_db`), `ensure_migrations_table()` creates the `schema_migrations` tracking table.
- `run_pending(engine)` scans this directory for `*.py` files sorted by filename and runs any that haven't been applied yet.

## Writing a new migration

1. Create a new file here named `NNNN_short_description.py` where `NNNN` is a zero-padded 4-digit sequence number (e.g. `0002_add_index_to_signals.py`).
2. The file must define three things at module level:

```python
MIGRATION_ID = "0002_add_index_to_signals"   # must be unique across all migrations
DESCRIPTION  = "Add composite index on signals(strategy_id, date)"

def up(conn):
    """Receives a sqlite3.Connection. Must be idempotent where possible."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_signals_strategy_date "
        "ON signals(strategy_id, date)"
    )
```

3. `up(conn)` receives a raw `sqlite3.Connection`. The engine wraps the call in a transaction; if it raises, the transaction is rolled back and the error re-raised (migration is NOT recorded as applied).

## Rules

- **Sequence numbers must be contiguous** — don't skip numbers.
- **Never edit a migration that has already been applied** to any environment. Add a new one instead.
- `up()` should be **idempotent** (`IF NOT EXISTS`, `IF EXISTS` guards) so it is safe to replay on a fresh DB.
- Keep each migration small and focused. One schema change per file.
- `MIGRATION_ID` must exactly match the filename stem (without `.py`).

## Applied migrations

The `schema_migrations` table in `aqrti.db` is the source of truth:

```sql
SELECT migration_id, applied_at, description FROM schema_migrations ORDER BY id;
```

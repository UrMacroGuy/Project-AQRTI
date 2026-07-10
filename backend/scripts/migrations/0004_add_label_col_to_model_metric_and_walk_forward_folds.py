"""
Migration 0004 — Add label_col to model_metrics and walk_forward_folds

SQLite requires table rebuild for constraint/index changes, so both tables
are rebuilt with the new column and updated constraints.

model_metrics:    adds label_col column, widens index to include it
walk_forward_folds: adds label_col column, widens unique constraint to include it
"""

MIGRATION_ID = "0004_add_label_col_to_model_metric_and_walk_forward_folds"
DESCRIPTION = "Add label_col to model_metrics and walk_forward_folds tables"


def up(conn):
    # --- model_metrics ---
    conn.execute("""
        CREATE TABLE model_metrics_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name      VARCHAR(20) NOT NULL,
            task            VARCHAR(30) NOT NULL,
            label_col       VARCHAR(40) NOT NULL DEFAULT '',
            version         INTEGER NOT NULL DEFAULT 1,
            fold            INTEGER,
            metric_name     VARCHAR(40) NOT NULL,
            metric_value    FLOAT NOT NULL,
            split           VARCHAR(10) NOT NULL DEFAULT 'test',
            computed_at     DATETIME NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO model_metrics_new (
            id, model_name, task, version, fold,
            metric_name, metric_value, split, computed_at
        )
        SELECT
            id, model_name, task, version, fold,
            metric_name, metric_value, split, computed_at
        FROM model_metrics
    """)
    conn.execute("DROP TABLE model_metrics")
    conn.execute("ALTER TABLE model_metrics_new RENAME TO model_metrics")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_mm_model_task_label ON model_metrics (model_name, task, label_col)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_mm_computed_at ON model_metrics (computed_at)")

    # --- walk_forward_folds ---
    conn.execute("""
        CREATE TABLE walk_forward_folds_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name      VARCHAR(20) NOT NULL,
            task            VARCHAR(30) NOT NULL,
            label_col       VARCHAR(40) NOT NULL DEFAULT '',
            version         INTEGER NOT NULL DEFAULT 1,
            fold            INTEGER NOT NULL,
            train_start     VARCHAR(12),
            train_end       VARCHAR(12),
            test_start      VARCHAR(12),
            test_end        VARCHAR(12),
            train_rows      INTEGER,
            test_rows       INTEGER,
            status          VARCHAR(20) DEFAULT 'pending',
            UNIQUE (model_name, task, label_col, version, fold)
        )
    """)
    conn.execute("""
        INSERT INTO walk_forward_folds_new (
            id, model_name, task, version, fold,
            train_start, train_end, test_start, test_end,
            train_rows, test_rows, status
        )
        SELECT
            id, model_name, task, version, fold,
            train_start, train_end, test_start, test_end,
            train_rows, test_rows, status
        FROM walk_forward_folds
    """)
    conn.execute("DROP TABLE walk_forward_folds")
    conn.execute("ALTER TABLE walk_forward_folds_new RENAME TO walk_forward_folds")

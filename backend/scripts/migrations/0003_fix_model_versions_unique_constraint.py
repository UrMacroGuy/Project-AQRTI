"""
Migration 0003 — Fix model_versions unique constraint (C13/label_col collision)

The original UNIQUE(model_name, task, version) constraint assumed one
label_col per task, which was true when direction_5d was the only label
under task="direction". It no longer is: outperform_binary also has
task="direction", so registering its model hit
"UNIQUE constraint failed: model_versions.model_name, model_versions.task,
model_versions.version" — the exact row that should have been created for
outperform_binary was rejected because (catboost, direction, 1) already
existed for direction_5d.

SQLite has no ALTER TABLE ... DROP CONSTRAINT, so this rebuilds the table
with the corrected UNIQUE(model_name, task, label_col, version) constraint,
copies existing rows across, then swaps it in.
"""

MIGRATION_ID = "0003_fix_model_versions_unique_constraint"
DESCRIPTION = "model_versions: widen unique constraint to include label_col"


def up(conn):
    conn.execute("""
        CREATE TABLE model_versions_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name      VARCHAR(20) NOT NULL,
            task            VARCHAR(30) NOT NULL,
            label_col       VARCHAR(40) NOT NULL,
            version         INTEGER NOT NULL DEFAULT 1,
            artifact_path   TEXT,
            primary_metric  FLOAT,
            metrics_json    TEXT,
            importance_json TEXT,
            train_rows      INTEGER,
            trained_at      DATETIME,
            is_active       BOOLEAN DEFAULT 0,
            UNIQUE (model_name, task, label_col, version)
        )
    """)
    conn.execute("""
        INSERT INTO model_versions_new (
            id, model_name, task, label_col, version, artifact_path,
            primary_metric, metrics_json, importance_json, train_rows,
            trained_at, is_active
        )
        SELECT
            id, model_name, task, label_col, version, artifact_path,
            primary_metric, metrics_json, importance_json, train_rows,
            trained_at, is_active
        FROM model_versions
    """)
    conn.execute("DROP TABLE model_versions")
    conn.execute("ALTER TABLE model_versions_new RENAME TO model_versions")
    conn.execute("CREATE INDEX ix_model_versions_model_name ON model_versions (model_name)")
    conn.execute("CREATE INDEX ix_model_versions_is_active ON model_versions (is_active)")

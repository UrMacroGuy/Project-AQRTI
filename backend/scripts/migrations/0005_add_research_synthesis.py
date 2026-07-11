"""
Migration 0005 — Add research_synthesis table

LLM-derived daily research synthesis per symbol (news + filings + earnings
-> structured thesis JSON). Every row must trace to real source_event_ids;
citation validation happens in application code (research_synthesizer.py)
before a row is ever inserted here.
"""

MIGRATION_ID = "0005_add_research_synthesis"
DESCRIPTION = "Add research_synthesis table for LLM research-to-strategy synthesis"


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_synthesis (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol                  VARCHAR(20) NOT NULL,
            synthesis_date          DATE NOT NULL,
            sentiment_score         FLOAT NOT NULL,
            thesis_direction        VARCHAR(10) NOT NULL,
            key_catalysts           TEXT,
            risk_flags              TEXT,
            management_change_flag  BOOLEAN NOT NULL DEFAULT 0,
            source_event_ids        TEXT NOT NULL,
            raw_response            TEXT,
            model_used              VARCHAR(60) NOT NULL,
            confidence               FLOAT,
            created_at              DATETIME NOT NULL,
            UNIQUE (symbol, synthesis_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_rs_symbol ON research_synthesis (symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_rs_date ON research_synthesis (synthesis_date)")

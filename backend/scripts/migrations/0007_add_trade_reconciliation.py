"""
Migration 0007 — Trade Reconciliation bridge table

Creates trade_reconciliations, a read-only reporting table linking algo
suggestions (paper_positions) to the real transaction that acted on them
(portfolio_transactions), by ID only. Never merges the two source tables'
semantics — see CLAUDE.md "Personal Portfolio module" section.
"""

MIGRATION_ID = "0007_add_trade_reconciliation"
DESCRIPTION = "Create trade_reconciliations bridge table for slippage/hesitation tracking"


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_reconciliations (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol               TEXT    NOT NULL,
            algo_suggestion_id   INTEGER REFERENCES paper_positions(id),
            algo_suggested_price REAL    NOT NULL,
            algo_suggested_date  DATE    NOT NULL,
            strategy_id          TEXT,
            strategy_name        TEXT,
            human_transaction_id INTEGER REFERENCES portfolio_transactions(id),
            human_fill_price     REAL,
            human_fill_date      DATE,
            slippage_pct         REAL,
            days_to_fill         INTEGER,
            outcome_if_taken     REAL,
            status               TEXT    NOT NULL DEFAULT 'suggested_only',
            created_at           DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS ix_tr_symbol ON trade_reconciliations (symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS ix_tr_status ON trade_reconciliations (status)
    """)

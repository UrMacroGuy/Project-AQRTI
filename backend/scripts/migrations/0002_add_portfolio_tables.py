"""
Migration 0002 — Personal Portfolio tables (PF-2)

Creates the 6 portfolio-tracking tables for the My Portfolio module,
fully separate from the paper-trading layer.
"""

MIGRATION_ID = "0002_add_portfolio_tables"
DESCRIPTION = "Create personal portfolio tracking tables"


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_instruments (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker                TEXT    NOT NULL UNIQUE,
            asset_class           TEXT    NOT NULL,
            fund_name             TEXT,
            amfi_code             TEXT    UNIQUE,
            isin                  TEXT,
            currency              TEXT    NOT NULL DEFAULT 'INR',
            target_allocation_pct REAL,
            risk_bucket           TEXT    NOT NULL DEFAULT 'core',
            verification_status   TEXT    NOT NULL DEFAULT 'pending',
            created_at            DATETIME NOT NULL DEFAULT (datetime('now')),
            updated_at            DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker           TEXT    NOT NULL,
            transaction_type TEXT    NOT NULL,
            quantity         REAL    NOT NULL,
            price            REAL    NOT NULL,
            amount           REAL    NOT NULL,
            transaction_date DATE    NOT NULL,
            broker           TEXT    NOT NULL DEFAULT 'manual',
            note             TEXT,
            created_at       DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS ix_pt_ticker_date
            ON portfolio_transactions (ticker, transaction_date)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_holdings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT    NOT NULL,
            quantity        REAL    NOT NULL,
            avg_cost        REAL    NOT NULL,
            current_price   REAL,
            current_value   REAL,
            unrealized_pnl  REAL,
            realized_pnl    REAL,
            xirr            REAL,
            as_of_date      DATE    NOT NULL,
            created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
            UNIQUE (ticker, as_of_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_valuations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date          DATE    NOT NULL UNIQUE,
            total_value         REAL    NOT NULL,
            total_cost          REAL    NOT NULL,
            total_unrealized_pnl REAL,
            total_realized_pnl  REAL,
            cash_balance        REAL    NOT NULL,
            xirr                REAL,
            created_at          DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mutual_fund_navs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            amfi_code   TEXT    NOT NULL,
            scheme_name TEXT,
            nav         REAL    NOT NULL,
            nav_date    DATE    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'amfi',
            created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
            UNIQUE (amfi_code, nav_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_action_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type  TEXT    NOT NULL,
            description  TEXT,
            due_date     DATE,
            status       TEXT    NOT NULL DEFAULT 'pending',
            completed_at DATETIME,
            created_at   DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

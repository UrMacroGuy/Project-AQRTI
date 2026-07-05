"""
Migration: add OOS columns to strategies_v2 + deactivate dead Stock rows.

Idempotent — safe to re-run. Run with the server STOPPED.

1. ALTER TABLE strategies_v2 ADD oos_sharpe/oos_win_rate/oos_trades/oos_passed
2. Deactivate Stock rows whose symbol has an exchange suffix but no price
   data (dead entries created by the old ticker_to_symbol convention).
3. Deactivate known-fictitious legacy tickers (LTM, TMPV variants).
"""

import sqlite3, os, sys

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aqrti.db")

def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=30000")
    cur = con.cursor()

    # 1. OOS columns (idempotent via PRAGMA check)
    existing = {r[1] for r in cur.execute("PRAGMA table_info(strategies_v2)")}
    for col, ddl in [
        ("oos_sharpe",   "ALTER TABLE strategies_v2 ADD COLUMN oos_sharpe FLOAT"),
        ("oos_win_rate", "ALTER TABLE strategies_v2 ADD COLUMN oos_win_rate FLOAT"),
        ("oos_trades",   "ALTER TABLE strategies_v2 ADD COLUMN oos_trades INTEGER"),
        ("oos_passed",   "ALTER TABLE strategies_v2 ADD COLUMN oos_passed BOOLEAN"),
    ]:
        if col not in existing:
            cur.execute(ddl)
            print(f"Added column: {col}")
        else:
            print(f"Column exists: {col}")

    # 2. Deactivate suffixed Stock rows with no price data
    cur.execute("""
        UPDATE stocks SET active = 0
        WHERE symbol LIKE '%.%'
          AND symbol NOT IN (SELECT DISTINCT symbol FROM daily_prices)
          AND active = 1
    """)
    print(f"Deactivated {cur.rowcount} dead suffixed Stock rows")

    # 3. Fictitious legacy tickers
    cur.execute("""
        UPDATE stocks SET active = 0
        WHERE symbol IN ('LTM', 'TMPV', 'LTM.NS', 'TMPV.NS') AND active = 1
    """)
    print(f"Deactivated {cur.rowcount} legacy ticker rows")

    con.commit()

    # Report
    n_active = cur.execute("SELECT COUNT(*) FROM stocks WHERE active = 1").fetchone()[0]
    n_priced = cur.execute("SELECT COUNT(DISTINCT symbol) FROM daily_prices").fetchone()[0]
    print(f"Active stocks: {n_active} | symbols with prices: {n_priced}")
    con.close()

if __name__ == "__main__":
    main()

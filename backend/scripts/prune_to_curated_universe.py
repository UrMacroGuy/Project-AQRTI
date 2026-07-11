"""
Prune AQRTI's DB down to a 12-symbol curated universe.

Approved architecture plan universe (KEEP, exact symbol match, case-sensitive):
  Tier 1 (owned): BEL, HDFCBANK, NTPC, NIFTY 50 index (index_data, untouched), VOO, QQQ
  Tier 2 (bench): ICICIBANK, INFY, CDSL, DRREDDY, LT, HAL

NOTE ON "NIFTY 50": the `index_data` table stores the NIFTY series under
`index_name == "NIFTY50"` (no space, no `.symbol` — see IndexData model /
regime_discovery.py / strategy_lifecycle.py / snapshot_manager.py). IndexData
is not touched by this script at all (kept whole per spec), so no symbol
matching is needed for it.

SYMBOL FORM: `stocks.symbol` is stored WITHOUT an exchange suffix for the
live/active row (e.g. "BEL", "HDFCBANK"). Legacy scraper runs also left
behind `SYMBOL.NS` / `SYMBOL.BO` duplicate rows, already marked
`active=0` by a prior migration (migrate_oos_and_cleanup.py). Those
suffixed duplicates are NOT in the exact 12-symbol keep-list below, so
they fall out of the universe and get pruned along with every other
non-universe stock. Matching is EXACT STRING EQUALITY, case-sensitive —
never LIKE/substring (a substring match on "LT" would also catch
"LTTS", "ULTRACEMCO", "HCLTECH via 'LT'", etc. — verified against the
live DB during script authoring).

VOO, QQQ, and CDSL do not currently exist as rows in `stocks` (verified
against the live DB: zero rows for any of the three). That's fine —
this script only deletes what's there; it never fabricates or inserts
placeholder rows for missing universe symbols.

Usage:
    python scripts/prune_to_curated_universe.py                # refuses, prints plan (dry-run-like)
    python scripts/prune_to_curated_universe.py --dry-run       # prints counts + planned order only
    python scripts/prune_to_curated_universe.py --yes           # actually executes

Always run with the backend server STOPPED (avoid "database is locked").
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import date

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aqrti.db")

# ══════════════════════════════════════════════════════════════════════════
# UNIVERSE TO KEEP — exact, case-sensitive symbol match against stocks.symbol
# ══════════════════════════════════════════════════════════════════════════
KEEP_SYMBOLS = [
    # Tier 1 — owned
    "BEL", "HDFCBANK", "NTPC", "VOO", "QQQ",
    # Tier 2 — bench
    "ICICIBANK", "INFY", "CDSL", "DRREDDY", "LT", "HAL",
]
# NIFTY 50 is index_data.index_name == "NIFTY50" — a separate table, kept
# whole, not part of this symbol list.

# ══════════════════════════════════════════════════════════════════════════
# CATEGORY A — wipe entirely, unconditionally, regardless of symbol.
# Order matters: children (tables with a logical/DB FK to a parent in this
# same list) are deleted before their parents.
# ══════════════════════════════════════════════════════════════════════════

# Strategy family. strategy_versions/strategy_performance carry a REAL
# SQLAlchemy ForeignKey("strategies_v2.strategy_id"); everything else in
# this family (graveyard, evolution_history, backtest_trades, dna, memory,
# archive, research_reports, legacy `strategies`) is linked only by a plain
# string strategy_id column (no DB-level FK) but is still logically a child
# of the strategy population, so it is wiped in full together with it.
STRATEGY_TABLES_WIPE_ALL = [
    "strategy_versions",            # FK -> strategies_v2.strategy_id
    "strategy_performance",         # FK -> strategies_v2.strategy_id
    "strategy_evolution_history",   # string strategy_id, no DB FK
    "strategy_backtest_trades",     # string strategy_id, no DB FK
    "strategy_graveyard",           # string strategy_id, no DB FK
    "strategy_dna",                 # string strategy_id, no DB FK
    "strategy_memory",              # string strategy_id, no DB FK
    "strategy_archive",             # string strategy_id, no DB FK
    "strategy_research_reports",    # not strategy-keyed, but strategy-population-derived report table
    "strategies_v2",                # parent
    "strategies",                   # legacy v1 table, independent, no children
]

# ML family. No table in this file declares a real ForeignKey to
# model_versions/model_registry — all links are plain string/name columns
# (model_name, model_id) — so there is no DB-level ordering requirement
# among them, but we still delete "detail" tables before the registries for
# clarity for a human reading the transaction log.
ML_TABLES_WIPE_ALL = [
    "model_metrics",           # model_name/task/label_col, no DB FK
    "model_drift_history",     # model_name, no DB FK
    "model_weights",           # model_name, no DB FK
    "walk_forward_folds",      # model_name/task/label_col, no DB FK
    "model_memory",            # model_name, no DB FK
    "predictions",             # FK -> stocks.symbol (see CATEGORY B note below on why
                                # this table is wiped in full rather than per-symbol:
                                # predictions.symbol is not in the "wipe non-universe
                                # symbols only" list the plan specified, but it holds a
                                # real FK to stocks.symbol; the plan's underlying paper
                                # trading tables are wiped wholesale anyway, so predictions
                                # (which exists only to feed paper trading / arena) is
                                # wiped wholesale too rather than left half-orphaned)
    "prediction_archive",      # symbol column, no DB FK, immutable archive of predictions above
    "prediction_patterns",     # not symbol-keyed
    "model_versions",          # parent registry
    "model_registry",          # legacy v1 registry, independent
]

PAPER_TRADING_TABLES_WIPE_ALL = [
    "paper_positions",   # FK -> predictions.id (nullable) + logical FK -> paper_portfolios.portfolio_name
    "paper_trades",      # FK -> predictions.id (nullable) + logical FK -> paper_portfolios.portfolio_name
    "paper_portfolios",  # parent
]

MARKOV_TABLES_WIPE_ALL = [
    "markov_strategies",        # independent population, string strategy_id, no DB FK
    "markov_hmm_regime_daily",  # independent
    "markov_hmm_models",        # independent
    "markov_chain_daily",       # independent
    "markov_watchlist",         # persistent symbol watchlist — regenerate clean too
]

# ══════════════════════════════════════════════════════════════════════════
# CATEGORY B — wipe rows for symbols NOT in KEEP_SYMBOLS only.
# All of these have a plain `symbol` (or `company`) column; only
# FeatureValue has a real DB-level ForeignKey("stocks.symbol"), but all are
# logically keyed off Stock and must be pruned in lockstep with `stocks`.
# Order: children before the `stocks` parent itself.
# ══════════════════════════════════════════════════════════════════════════
PER_SYMBOL_TABLES = [
    ("daily_prices",           "symbol"),   # FK -> stocks.symbol
    ("feature_values",         "symbol"),   # FK -> stocks.symbol
    ("news_events",            "company"),  # nullable company column
    ("sentiment_records",      "entity"),   # entity_type may be 'stock'|'sector'|'market' — see caveat below
    ("nse_corporate_filings",  "symbol"),
    ("earnings_events",        "symbol"),
    ("options_data",           "symbol"),   # deprecated table, still listed explicitly by the plan
    ("options_chain",          "symbol"),
    ("entity_mentions",        "symbol"),
]
# CAVEAT on sentiment_records: `entity` also holds sector names ("IT",
# "Banking") and the literal market entity when entity_type='market'/'sector'.
# We only delete rows where entity_type='stock' AND entity not in
# KEEP_SYMBOLS, so sector/market-level sentiment rows are left untouched
# regardless of their entity string.

STOCKS_TABLE = "stocks"

# ══════════════════════════════════════════════════════════════════════════
# NEVER TOUCH — real-money audit trail. Not referenced anywhere below.
# ══════════════════════════════════════════════════════════════════════════
# portfolio_instruments, portfolio_transactions, portfolio_holdings,
# portfolio_valuations, mutual_fund_navs, portfolio_action_logs


def backup_db(db_path: str) -> str:
    if not os.path.exists(db_path):
        raise SystemExit(f"REFUSING: DB not found at {db_path}")
    stamp = date.today().strftime("%Y%m%d")
    backup_path = f"{db_path}.bak-{stamp}"
    if os.path.exists(backup_path):
        print(f"Backup already exists at {backup_path} (from an earlier run today) — reusing it, not overwriting.")
        return backup_path
    try:
        shutil.copy2(db_path, backup_path)
    except Exception as exc:
        raise SystemExit(f"REFUSING: backup copy failed ({exc}). No changes made.")
    if not os.path.exists(backup_path) or os.path.getsize(backup_path) != os.path.getsize(db_path):
        raise SystemExit("REFUSING: backup copy verification failed (size mismatch). No changes made.")
    print(f"Backup written: {backup_path} ({os.path.getsize(backup_path):,} bytes)")
    return backup_path


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def count_rows(cur: sqlite3.Cursor, table: str) -> int:
    if not table_exists(cur, table):
        return -1  # sentinel: table missing from this DB
    return cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def count_non_universe_rows(cur: sqlite3.Cursor, table: str, col: str) -> int:
    if not table_exists(cur, table):
        return -1
    placeholders = ",".join("?" for _ in KEEP_SYMBOLS)
    query = f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL OR {col} NOT IN ({placeholders})"
    if table == "sentiment_records":
        query = (
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE entity_type = 'stock' AND (entity IS NULL OR entity NOT IN ({placeholders}))"
        )
    return cur.execute(query, KEEP_SYMBOLS).fetchone()[0]


def print_counts(cur: sqlite3.Cursor, label: str) -> None:
    print(f"\n--- {label} ---")
    print("\n[Category A: full wipe]")
    for group_name, tables in [
        ("strategy", STRATEGY_TABLES_WIPE_ALL),
        ("ML", ML_TABLES_WIPE_ALL),
        ("paper trading", PAPER_TRADING_TABLES_WIPE_ALL),
        ("markov", MARKOV_TABLES_WIPE_ALL),
    ]:
        for t in tables:
            n = count_rows(cur, t)
            tag = "(missing)" if n < 0 else f"{n:,} rows"
            print(f"  [{group_name:12s}] {t:32s} {tag}")

    print("\n[Category B: non-universe symbol rows]")
    for t, col in PER_SYMBOL_TABLES:
        total = count_rows(cur, t)
        non_univ = count_non_universe_rows(cur, t, col)
        if total < 0:
            print(f"  {t:24s} (missing)")
        else:
            print(f"  {t:24s} total={total:,}  to_delete={non_univ:,}  kept={total - non_univ:,}")

    total_stocks = count_rows(cur, STOCKS_TABLE)
    if total_stocks >= 0:
        placeholders = ",".join("?" for _ in KEEP_SYMBOLS)
        kept = cur.execute(
            f"SELECT COUNT(*) FROM {STOCKS_TABLE} WHERE symbol IN ({placeholders})", KEEP_SYMBOLS
        ).fetchone()[0]
        print(f"\n  {STOCKS_TABLE:24s} total={total_stocks:,}  to_delete={total_stocks - kept:,}  kept={kept:,}")
        found = cur.execute(
            f"SELECT symbol FROM {STOCKS_TABLE} WHERE symbol IN ({placeholders})", KEEP_SYMBOLS
        ).fetchall()
        found_syms = {r[0] for r in found}
        missing = [s for s in KEEP_SYMBOLS if s not in found_syms]
        if missing:
            print(f"  NOTE: these keep-list symbols have no row in `stocks` at all "
                  f"(nothing to keep/delete for them): {missing}")


def run_phase(con: sqlite3.Connection, label: str, statements: list[tuple[str, tuple]]) -> None:
    cur = con.cursor()
    print(f"\n=== Phase: {label} ===")
    try:
        for sql, params in statements:
            cur.execute(sql, params)
            print(f"  {cur.rowcount:>8,} deleted  <-  {sql}")
        con.commit()
    except Exception:
        con.rollback()
        raise


def build_statements(cur: sqlite3.Cursor) -> tuple[list, list, list, list, list]:
    """Return (strategy_stmts, ml_stmts, paper_stmts, markov_stmts, per_symbol_stmts)."""
    strategy_stmts = [
        (f"DELETE FROM {t}", ()) for t in STRATEGY_TABLES_WIPE_ALL if table_exists(cur, t)
    ]
    ml_stmts = [
        (f"DELETE FROM {t}", ()) for t in ML_TABLES_WIPE_ALL if table_exists(cur, t)
    ]
    paper_stmts = [
        (f"DELETE FROM {t}", ()) for t in PAPER_TRADING_TABLES_WIPE_ALL if table_exists(cur, t)
    ]
    markov_stmts = [
        (f"DELETE FROM {t}", ()) for t in MARKOV_TABLES_WIPE_ALL if table_exists(cur, t)
    ]

    placeholders = ",".join("?" for _ in KEEP_SYMBOLS)
    per_symbol_stmts = []
    for t, col in PER_SYMBOL_TABLES:
        if not table_exists(cur, t):
            continue
        if t == "sentiment_records":
            sql = (
                f"DELETE FROM {t} WHERE entity_type = 'stock' "
                f"AND (entity IS NULL OR entity NOT IN ({placeholders}))"
            )
        else:
            sql = f"DELETE FROM {t} WHERE {col} IS NULL OR {col} NOT IN ({placeholders})"
        per_symbol_stmts.append((sql, tuple(KEEP_SYMBOLS)))

    # stocks itself, deleted last within Category B
    per_symbol_stmts.append(
        (f"DELETE FROM {STOCKS_TABLE} WHERE symbol NOT IN ({placeholders})", tuple(KEEP_SYMBOLS))
    )

    return strategy_stmts, ml_stmts, paper_stmts, markov_stmts, per_symbol_stmts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune aqrti.db down to the 12-symbol curated universe."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Print counts and planned deletion order only. No changes.")
    parser.add_argument("--yes", action="store_true",
                         help="Required to actually execute deletions.")
    args = parser.parse_args()

    print(f"DB path: {DB_PATH}")
    print(f"Keep-list ({len(KEEP_SYMBOLS)} symbols): {KEEP_SYMBOLS}")
    print("NIFTY 50 lives in index_data.index_name == 'NIFTY50' and is never touched by this script.")

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"REFUSING: DB not found at {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA busy_timeout=30000")
    cur = con.cursor()

    print_counts(cur, "BEFORE (current state)")

    strategy_stmts, ml_stmts, paper_stmts, markov_stmts, per_symbol_stmts = build_statements(cur)

    print("\n=== Planned deletion order ===")
    print("1. strategy family (children -> parents):", [s for s, _ in strategy_stmts])
    print("2. ML family:                            ", [s for s, _ in ml_stmts])
    print("3. paper trading (children -> parent):   ", [s for s, _ in paper_stmts])
    print("4. markov (independent, any order):      ", [s for s, _ in markov_stmts])
    print("5. per-symbol tables, then stocks itself: ", [s for s, _ in per_symbol_stmts])

    if args.dry_run or not args.yes:
        con.close()
        if not args.dry_run:
            print("\nREFUSING to execute without --yes. Re-run with --dry-run to only preview, "
                  "or --yes to actually delete.")
        else:
            print("\n--dry-run: no changes made.")
        return

    # --yes: back up first, then execute for real.
    backup_db(DB_PATH)

    run_phase(con, "1/5 strategy family", strategy_stmts)
    run_phase(con, "2/5 ML family", ml_stmts)
    run_phase(con, "3/5 paper trading", paper_stmts)
    run_phase(con, "4/5 markov", markov_stmts)
    run_phase(con, "5/5 per-symbol + stocks", per_symbol_stmts)

    con.execute("VACUUM")

    cur = con.cursor()
    print_counts(cur, "AFTER (post-deletion state)")

    con.close()
    print("\nDone. Backup preserved at aqrti.db.bak-<date> in case of rollback.")


if __name__ == "__main__":
    main()

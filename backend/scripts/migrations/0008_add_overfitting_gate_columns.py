"""
Migration 0008 — Overfitting / multiple-testing diagnostic columns on
strategies_v2

Adds the columns backing the new Monte Carlo permutation test and Deflated
Sharpe Ratio (Lopez de Prado) validation stats, per CLAUDE.md's "prosecute
your own results" standard:

  mc_bankruptcy_pct   — % of shuffled trade-return orderings (Monte Carlo
                        permutation test, strategy_metrics.py) whose
                        compounding equity curve goes bust. High values mean
                        the strategy's apparent edge depends on a lucky
                        sequence of wins/losses, not a genuine order-
                        independent edge.
  mc_worse_sharpe_pct — % of those shuffles whose Sharpe is worse than the
                        actual (unshuffled) trade order's Sharpe.
  deflated_sharpe     — Deflated Sharpe Ratio statistic (Bailey & Lopez de
                        Prado 2014): P(true Sharpe > 0), corrected for
                        multiple-testing across n_trials template variants
                        and for skew/kurtosis of the trade-return
                        distribution. 0..1, NOT a rescaled Sharpe number.

Enforced at promotion by promotion_config.MC_MAX_BANKRUPTCY_PCT (15.0) and
MIN_DEFLATED_SHARPE_PROB (0.95) — see strategy_lifecycle.promote_strategy.
"""

MIGRATION_ID = "0008_add_overfitting_gate_columns"
DESCRIPTION = "Add mc_bankruptcy_pct, mc_worse_sharpe_pct, deflated_sharpe columns to strategies_v2"


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def up(conn):
    if not _has_column(conn, "strategies_v2", "mc_bankruptcy_pct"):
        conn.execute(
            "ALTER TABLE strategies_v2 ADD COLUMN mc_bankruptcy_pct FLOAT"
        )
    if not _has_column(conn, "strategies_v2", "mc_worse_sharpe_pct"):
        conn.execute(
            "ALTER TABLE strategies_v2 ADD COLUMN mc_worse_sharpe_pct FLOAT"
        )
    if not _has_column(conn, "strategies_v2", "deflated_sharpe"):
        conn.execute(
            "ALTER TABLE strategies_v2 ADD COLUMN deflated_sharpe FLOAT"
        )

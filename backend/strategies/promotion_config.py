"""
Promotion Config — single source of truth for strategy promotion/retirement
gates. Import from here; do NOT re-declare these constants elsewhere.

Rationale for values:
  MIN_BACKTEST_TRADES = 60  — over the ~2.5yr in-sample window the empirical
      per-strategy trade count averages ~52 (max ~430). 60 gives a ±6pp
      95% CI on win-rate; the old 300 was unreachable for most designs and
      the old 10 was statistical noise.
  MIN_SHARPE = 0.5 — on the HONEST daily mark-to-market Sharpe scale
      (post-2026-07 backtester fix). Recalibrate against the population
      distribution after each full re-score, not against the old inflated
      per-trade-repeat Sharpe scale.
  OOS gates — a strategy must PROVE itself on the held-out 6-month window
      (embargoed walk-forward) before promotion. This is a hard gate.
"""

# Backtest quality gates (promotion)
PROMOTE_THRESHOLD    = 50.0   # composite fitness 0-100
MIN_BACKTEST_TRADES  = 60
MIN_WIN_RATE         = 52.0   # % — must beat coin flip with margin
MIN_SHARPE           = 0.5    # honest daily-series Sharpe

# Out-of-sample hard gates (promotion)
REQUIRE_OOS_PASS     = True
MIN_OOS_SHARPE       = 0.2
# MIN_OOS_WIN_RATE — additional floor enforced at the OOS stage, stacking on
# top of (never replacing) the existing oos_passed/oos_sharpe gates above.
# strategy_backtester._walk_forward_oos_check already requires oos_win_rate
# >= 50.0 internally to set oos_passed=True, but that 50.0 floor was never
# exposed as an independently-checkable named constant nor re-verified at
# promotion time — this makes the 50% OOS win-rate floor explicit and
# enforced directly in promote_strategy, matching the pattern of the
# MIN_OOS_SHARPE check immediately below it.
MIN_OOS_WIN_RATE     = 50.0

# Benchmark gate (promotion): the strategy's honest daily Sharpe must reach
# at least this fraction of buy-and-hold NIFTY50's Sharpe over the same
# window. A strategy that can't approach doing-nothing is not worth capital.
BENCHMARK_SHARPE_FACTOR = 0.8

# Duplicate detection (promotion): reject promotion if the candidate's
# backtest trades overlap an already-promoted strategy's by more than this
# Jaccard similarity on (symbol, entry_date). Near-clones add risk, not edge.
MAX_TRADE_OVERLAP = 0.60

# Retirement
RETIRE_THRESHOLD     = 15.0   # composite fitness floor
# Max drawdown gate — was hardcoded to -100.0 (effectively unreachable,
# meaning no strategy could ever be retired for a real drawdown blowout)
# with a comment claiming "fitness captures drawdown indirectly." Fitness
# does weight drawdown, but a strategy can still score above RETIRE_THRESHOLD
# on fitness/win-rate/Sharpe while carrying a catastrophic max_drawdown if
# its rare large losses are outweighed by many small wins — exactly the
# "picking up pennies in front of a steamroller" failure mode fitness alone
# doesn't reliably catch. Now computed against the HONEST daily
# mark-to-market max_drawdown (post-2026-07 backtester fix) rather than the
# old per-trade-chained pseudo-equity number, so this threshold means what
# it says: -35% peak-to-trough is a real, survivable-but-serious drawdown
# for a single strategy sized at the platform's default position sizing.
MAX_DRAWDOWN_LIMIT   = -35.0

# Paper-trading quarantine — a promoted strategy is NOT eligible for human
# approval to "active" until it has proven itself forward, on data that did
# not exist when it was created. This is the only test that cannot be
# overfit.
QUARANTINE_MIN_DAYS      = 60     # calendar days in promoted status
QUARANTINE_MIN_TRADES    = 20     # closed live paper trades
QUARANTINE_MIN_WIN_RATE  = 50.0   # % on those live trades
# (plus: live net P&L must be positive)

# Paper / live validation
PAPER_WIN_RATE_GATE      = 52.0   # % live paper win rate to stay promoted
RETRAIN_WIN_RATE_TARGET  = 52.0   # % — ML retrain trigger threshold

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

# ── Expectancy-gated families (USER DECISION, 2026-07-14) ──────────────
# Some documented edges are structurally low-win-rate/high-payoff: the lab
# measured 52-week-high momentum on this exact universe at 43.8% WR but
# +3.62%/trade NET of costs (docs/STRATEGY_LAB.md variant D) — the
# strongest raw edge found, permanently blocked by the WR floors above.
# The lab also proved WHY a WR floor alone is a trap: its OOS-failed
# finalist KEPT a 61.7% win rate while expectancy collapsed to
# -0.71%/trade. For the families listed here (and ONLY these), the
# in-sample/OOS/quarantine/live win-rate floors are REPLACED by all three
# of the checks below — every other gate (fitness, trades, Sharpe,
# oos_passed, benchmark, dedup, quarantine days/trades/P&L) is unchanged.
# This is an alternate proof standard, not a weakening: expectancy AND
# profit factor AND a TIGHTER drawdown cap must all hold, net of the
# 0.28% round-trip cost model.
EXPECTANCY_GATED_FAMILIES = {"week52_high_momentum"}
MIN_EXPECTANCY_PCT           = 1.0    # avg %/trade net of costs (lab edge measured +3.62%)
MIN_PROFIT_FACTOR_EXPECTANCY = 1.5    # gross wins / gross losses
# Tighter than the universal MAX_DRAWDOWN_LIMIT (-35.0): low-WR strategies
# run longer losing streaks by construction, so waiving the WR floor
# demands a stricter drawdown proof in exchange.
MAX_DRAWDOWN_EXPECTANCY      = -25.0


def is_expectancy_gated(family: str | None) -> bool:
    """True if this family promotes via the expectancy gate instead of WR floors."""
    return family in EXPECTANCY_GATED_FAMILIES


# Benchmark gate (promotion): the strategy's honest daily Sharpe must reach
# at least this fraction of buy-and-hold NIFTY50's Sharpe over the same
# window. A strategy that can't approach doing-nothing is not worth capital.
BENCHMARK_SHARPE_FACTOR = 0.8

# Duplicate detection (promotion): reject promotion if the candidate's
# backtest trades overlap an already-promoted strategy's by more than this
# Jaccard similarity on (symbol, entry_date). Near-clones add risk, not edge.
MAX_TRADE_OVERLAP = 0.60

# Retirement
# Raised from 15.0 -> 30.0 (2026-07-13) after fixing a fitness_engine.py bug
# where deeply negative Sharpe (down to -8.0) was clamped to a 0
# contribution on ONLY the Sharpe sub-term of profitability_score, letting
# strategies that lose money on every trade still earn full profit_factor/
# total_return credit and land at fitness 18-30 from win-rate/robustness/
# cost/regime/longevity components alone. 15.0 sat near the 5th percentile
# of the honest post-fix population (median 48, PROMOTE_THRESHOLD 50) and
# caught almost nothing. 30.0 sits below the 25th percentile -- retires the
# bottom quarter (including every Sharpe<-1 strategy, which now scores 0 on
# profitability per the fitness_engine.py fix) while still giving
# middling-but-not-broken candidates a chance to be refined by mutation
# before being cut. Recalibrate again after the next full re-score per the
# module docstring's standing guidance.
RETIRE_THRESHOLD     = 30.0   # composite fitness floor
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

# ── Overfitting / multiple-testing gates (added 2026-07-14) ────────────
# "Prosecute your own results" (CLAUDE.md): a good in-sample/OOS backtest
# can still be a lucky draw from a template-generation process that tries
# many variants. These two gates attack that risk directly, independent of
# the WR/Sharpe/expectancy gates above.
#
# MC_MAX_BANKRUPTCY_PCT — Monte Carlo permutation test
# (strategy_metrics.monte_carlo_permutation_test): shuffle the realized
# trade-return SEQUENCE n_simulations times and rebuild the compounding
# equity curve for each shuffle. If more than this % of shuffled orderings
# wipe out capital (cumulative equity <= 0), the strategy's apparent edge
# depends on a favorable path (e.g. early wins funding later losses) rather
# than a genuine order-independent edge — reject regardless of how good the
# unshuffled summary stats look.
MC_MAX_BANKRUPTCY_PCT    = 15.0

# MIN_DEFLATED_SHARPE_PROB — Deflated Sharpe Ratio (Bailey & Lopez de Prado
# 2014, strategy_metrics.compute_deflated_sharpe_ratio): the probability
# that the TRUE Sharpe ratio exceeds zero after correcting for (a) trying
# n_trials independent template/strategy variants and keeping only the best,
# and (b) non-normality (skew/kurtosis) of the trade-return distribution.
# 0.95 means the observed Sharpe must clear the expected-maximum-Sharpe-
# under-the-null benchmark by a wide enough margin that there's only a 5%
# chance the true edge is zero or negative once multiple-testing bias is
# priced in.
MIN_DEFLATED_SHARPE_PROB = 0.95

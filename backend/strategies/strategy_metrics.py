"""
Strategy Metrics
Computes rolling performance metrics for strategies from trade records.
Used by the fitness engine and the API.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta
from typing import Optional

import numpy as np
from scipy import stats as _scipy_stats

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import StrategyV2, StrategyPerformance
from aqrti.utils.logger import get_logger

log = get_logger("strategy_metrics")

# Daily risk-free rate in PERCENT units (all return series passed to these
# functions are in percent, e.g. 0.83 = 0.83%). 6.7% annual India T-bill.
RISK_FREE = 6.7 / 252   # ≈ 0.0266 %/day
ANNUALISE  = 252


def compute_sharpe(returns: list[float]) -> float:
    if len(returns) < 5:
        return 0.0
    arr  = np.array(returns)
    exc  = arr - RISK_FREE
    std  = exc.std()
    if std == 0:
        return 0.0
    sharpe = float(exc.mean() / std * np.sqrt(ANNUALISE))
    # Sane cap: a daily-series Sharpe above ~5 on Indian equities is a data
    # artifact, not skill. Bounds keep one corrupt bar from inflating the score.
    return round(max(min(sharpe, 8.0), -8.0), 4)


def compute_sortino(returns: list[float]) -> float:
    if len(returns) < 5:
        return 0.0
    arr      = np.array(returns)
    exc      = arr - RISK_FREE
    downside = arr[arr < 0]
    # Require enough downside observations for a meaningful downside deviation.
    # A sparse series (mostly 0.0 uninvested days + a couple of tiny negatives)
    # produces a near-zero ds_std that inflates Sortino to absurd values.
    if len(downside) < 3:
        return 0.0
    ds_std = downside.std()
    if ds_std == 0:
        # No downside dispersion → return 0, NOT inf. Deflationary on purpose.
        return 0.0
    sortino = float(exc.mean() / ds_std * np.sqrt(ANNUALISE))
    # Sane cap — Sortino should track Sharpe's order of magnitude, not explode.
    return round(max(min(sortino, 10.0), -10.0), 4)


def compute_max_drawdown(cumulative_returns: list[float]) -> float:
    """Returns max drawdown as a negative percentage."""
    if not cumulative_returns:
        return 0.0
    peak = -float("inf")
    mdd  = 0.0
    for v in cumulative_returns:
        if v > peak:
            peak = v
        dd = (v - peak) / (abs(peak) + 1e-9) * 100
        if dd < mdd:
            mdd = dd
    return round(mdd, 4)


def compute_profit_factor(gains: list[float], losses: list[float]) -> float:
    total_gain = sum(g for g in gains if g > 0)
    total_loss = sum(abs(l) for l in losses if l < 0)
    if total_loss == 0:
        # No losing trades → conservative cap, NOT 99. A small no-loss sample
        # would otherwise dominate every fitness weighting.
        return 5.0 if total_gain > 0 else 1.0
    return round(min(total_gain / total_loss, 10.0), 4)


def compute_expectancy(returns: list[float]) -> float:
    if not returns:
        return 0.0
    wins   = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_r  = len(wins) / len(returns)
    avg_w  = sum(wins) / len(wins)   if wins   else 0.0
    avg_l  = sum(losses) / len(losses) if losses else 0.0
    return round(win_r * avg_w + (1 - win_r) * avg_l, 4)


def monte_carlo_permutation_test(
    trade_returns: list[float],
    n_simulations: int = 1000,
) -> dict:
    """
    Monte Carlo permutation test on TRADE-LEVEL P&L ordering (not price data).

    The trade returns actually realized are fixed — what's being tested is
    whether the specific SEQUENCE they occurred in mattered. We shuffle the
    order of the same set of trade returns n_simulations times, rebuild the
    cumulative equity curve for each shuffle (compounding, percent units:
    each trade's pnl_pct applied as (1 + r/100)), and report:

      bankruptcy_pct   — % of shuffles whose cumulative equity curve hits
                          <= 0 at any point (i.e. cumulative product of
                          (1 + r) reaches zero or goes negative — total
                          capital wipeout under that ordering).
      worse_sharpe_pct — % of shuffles whose per-trade Sharpe (computed on
                          the shuffled trade-return series itself, same
                          formula as compute_sharpe) is worse than the
                          ORIGINAL unshuffled order's per-trade Sharpe.

    A strategy whose edge depends on a lucky ordering of wins/losses (e.g.
    early wins compounding before a late loss streak) will show high
    bankruptcy_pct even though the (order-independent) summary stats look
    fine — this is the "path risk" that expectancy/win-rate alone can't see.

    Honest by construction: if there are too few trades to say anything
    (< 5), returns 0/0 rather than fabricating a number from noise.
    """
    n = len(trade_returns)
    if n < 5 or n_simulations < 1:
        return {"bankruptcy_pct": 0.0, "worse_sharpe_pct": 0.0, "n_simulations": 0}

    arr = np.array(trade_returns, dtype=float)
    rng = np.random.default_rng()

    original_sharpe = compute_sharpe(trade_returns)

    n_bankrupt = 0
    n_worse_sharpe = 0
    for _ in range(n_simulations):
        shuffled = rng.permutation(arr)
        equity = np.cumprod(1.0 + shuffled / 100.0)
        if np.any(equity <= 0):
            n_bankrupt += 1
        shuffled_sharpe = compute_sharpe(shuffled.tolist())
        if shuffled_sharpe < original_sharpe:
            n_worse_sharpe += 1

    return {
        "bankruptcy_pct":   round(n_bankrupt / n_simulations * 100, 2),
        "worse_sharpe_pct": round(n_worse_sharpe / n_simulations * 100, 2),
        "n_simulations":    n_simulations,
    }


def compute_deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    n_returns: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, "The Deflated Sharpe
    Ratio: Correcting for Selection Bias, Backtest Overfitting and
    Non-Normality", 2014).

    Adjusts the observed Sharpe for two distortions:
      1. Multiple testing — trying n_trials independent strategy variants
         and reporting only the best one inflates the apparent Sharpe even
         under the null of zero true skill (the "expected maximum Sharpe"
         under repeated trials).
      2. Non-normality of returns — skew/kurtosis distort the standard
         error of the Sharpe estimator (higher moments matter at finite
         sample size).

    Returns the DSR STATISTIC itself: the probability (0..1) that the true
    Sharpe ratio exceeds zero, i.e. P(SR* > 0 | observed SR, n_trials,
    n_returns, skew, kurtosis). This is NOT a rescaled Sharpe number.

    n_trials=1 means no multiple-testing correction is applied (single
    strategy tested once) — callers evaluating one candidate against a
    known family/template count should pass that count explicitly.
    """
    if n_returns < 2 or n_trials < 1:
        return 0.0

    # Expected maximum Sharpe ratio across n_trials independent trials under
    # the null (true Sharpe = 0), from Bailey & Lopez de Prado eq. (7),
    # using the standard extreme-value approximation with the
    # Euler-Mascheroni constant. Variance of trial Sharpes is assumed 1.0
    # (standard normalized form of the expected-max formula).
    euler_mascheroni = 0.5772156649015329
    if n_trials <= 1:
        expected_max_sharpe = 0.0
    else:
        z1 = _scipy_stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = _scipy_stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
        expected_max_sharpe = (1 - euler_mascheroni) * z1 + euler_mascheroni * z2
        expected_max_sharpe = max(expected_max_sharpe, 0.0)

    # Standard error of the Sharpe ratio estimator adjusted for skew/kurtosis
    # (Bailey & Lopez de Prado eq. (5) / Mertens 2002).
    if n_returns <= 1:
        return 0.0
    sr_variance = (
        1
        - skew * sharpe
        + ((kurtosis - 1) / 4.0) * sharpe ** 2
    ) / (n_returns - 1)
    if sr_variance <= 0:
        sr_variance = 1e-9
    sr_std = np.sqrt(sr_variance)

    # DSR statistic: P(true SR > 0), i.e. how many standard errors the
    # observed Sharpe clears the expected-max-under-null benchmark.
    dsr = _scipy_stats.norm.cdf((sharpe - expected_max_sharpe) / sr_std)
    return round(float(max(min(dsr, 1.0), 0.0)), 4)


def live_performance_metrics(db: Session, strategy_id: str, days: int = 30) -> dict:
    """Compute live performance from StrategyPerformance records."""
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(StrategyPerformance)
        .filter(
            StrategyPerformance.strategy_id == strategy_id,
            StrategyPerformance.date        >= cutoff,
        )
        .order_by(StrategyPerformance.date.asc())
        .all()
    )
    if not rows:
        return {"days": days, "available": False}

    daily_pnl   = [r.daily_pnl_pct or 0.0 for r in rows]
    cum_pnl     = [r.cumulative_pnl or 0.0 for r in rows]
    total_wins  = sum(r.win_count  or 0 for r in rows)
    total_losses= sum(r.loss_count or 0 for r in rows)
    total_trades= total_wins + total_losses

    sharpe  = compute_sharpe(daily_pnl)
    sortino = compute_sortino(daily_pnl)
    mdd     = compute_max_drawdown(cum_pnl)
    win_rate= total_wins / total_trades * 100 if total_trades else 0.0

    return {
        "days":          days,
        "available":     True,
        "sharpe":        sharpe,
        "sortino":       sortino,
        "max_drawdown":  mdd,
        "win_rate":      round(win_rate, 2),
        "total_trades":  total_trades,
        "cumulative_pnl": round(cum_pnl[-1] if cum_pnl else 0.0, 4),
    }

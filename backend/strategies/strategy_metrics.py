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

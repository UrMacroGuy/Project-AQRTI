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

RISK_FREE = 0.067 / 252   # daily risk-free rate (approx. India T-bill)
ANNUALISE  = 252


def compute_sharpe(returns: list[float]) -> float:
    if len(returns) < 5:
        return 0.0
    arr  = np.array(returns)
    exc  = arr - RISK_FREE
    std  = exc.std()
    if std == 0:
        return 0.0
    return round(float(exc.mean() / std * np.sqrt(ANNUALISE)), 4)


def compute_sortino(returns: list[float]) -> float:
    if len(returns) < 5:
        return 0.0
    arr      = np.array(returns)
    exc      = arr - RISK_FREE
    downside = arr[arr < 0]
    ds_std   = downside.std() if len(downside) > 1 else 0.0
    if ds_std == 0:
        return 0.0
    return round(float(exc.mean() / ds_std * np.sqrt(ANNUALISE)), 4)


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
        return 99.0 if total_gain > 0 else 1.0
    return round(total_gain / total_loss, 4)


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

"""
Performance Tracker
Computes and persists all performance analytics for the paper portfolio.

Metrics:
  Total Return, Daily Return, CAGR, Sharpe, Sortino, Max Drawdown,
  Profit Factor, Win Rate, Expectancy, Exposure, Turnover
"""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import math
from datetime import date, timedelta
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from aqrti.database.models import EquityCurvePoint, PaperTrade, PerformanceSnapshot, IndexData
from aqrti.utils.logger import get_logger

log = get_logger("performance_tracker")

PORTFOLIO_NAME  = "default"
RISK_FREE_RATE  = 0.067    # ~6.7% annual (Indian T-bill proxy)
TRADING_DAYS    = 252

# Mirrors paper_portfolio._MAX_PLAUSIBLE_VALUE_RATIO — the peak used for
# drawdown here is MAX(total_value) over ALL historical EquityCurvePoint
# rows with no outlier filtering, so one corrupted row (a bad mark-to-market
# tick that slipped through) permanently sets a false all-time-high and
# every future day computes an inflated drawdown against it (2026-07-14:
# a fabricated ~9x total_value produced a -89% "critical drawdown" alert
# for a portfolio that was actually down <1%).
_MAX_PLAUSIBLE_VALUE_RATIO = 3.0


def _get_nifty_close(db: Session) -> Optional[float]:
    """Fetch today's Nifty50 close from IndexData, falling back to yfinance."""
    import logging
    _log = logging.getLogger(__name__)
    row = (
        db.query(IndexData.close)
        .filter(IndexData.index_name == "NIFTY50")
        .order_by(IndexData.date.desc())
        .first()
    )
    if row and row[0]:
        return float(row[0])
    _log.warning("IndexData has no NIFTY50 close — trying yfinance fallback")
    try:
        import yfinance as yf
        yf_stderr = StringIO()
        with redirect_stderr(yf_stderr):
            hist = yf.Ticker("^NSEI").history(period="2d", interval="1d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        _log.warning("yfinance fallback failed: %s", exc)
    _log.warning("All NIFTY50 close sources exhausted — returning None")
    return None


def record_equity_point(
    db:          Session,
    total_value: float,
    cash:        float,
    nifty_close: Optional[float] = None,
) -> EquityCurvePoint:
    """Upsert today's equity curve point with daily + cumulative returns."""
    today     = date.today()
    invested  = total_value - cash

    # Auto-fetch Nifty close if not provided
    if nifty_close is None:
        nifty_close = _get_nifty_close(db)

    # Previous row for daily return calc
    prev = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .order_by(EquityCurvePoint.date.desc())
        .first()
    )
    daily_ret   = 0.0
    cum_ret     = 0.0
    drawdown    = 0.0

    # Reject an implausible jump vs the last recorded point outright — a bad
    # mark-to-market tick must never become part of the permanent equity
    # curve history, since the drawdown calc below treats every historical
    # total_value as a candidate all-time-high peak with no outlier check.
    if prev and prev.total_value:
        ratio = max(total_value, prev.total_value) / max(min(total_value, prev.total_value), 1e-9)
        if ratio > _MAX_PLAUSIBLE_VALUE_RATIO:
            log.warning(
                "Rejected implausible equity curve point for %s: prev=%.2f new=%.2f "
                "(ratio=%.1fx > %.1fx) — not persisting, falling back to last known-good value",
                today, prev.total_value, total_value, ratio, _MAX_PLAUSIBLE_VALUE_RATIO,
            )
            total_value = prev.total_value
            cash        = prev.cash
            invested    = prev.invested

    if prev and prev.date < today:
        daily_ret = (total_value - prev.total_value) / prev.total_value * 100 if prev.total_value else 0.0

    # Cumulative return from all historical points
    first = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .order_by(EquityCurvePoint.date.asc())
        .first()
    )
    initial = first.total_value if first else total_value
    cum_ret = (total_value - initial) / initial * 100 if initial else 0.0

    # Current drawdown from rolling max
    max_val = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .order_by(EquityCurvePoint.total_value.desc())
        .first()
    )
    peak = max_val.total_value if max_val else total_value
    peak = max(peak, total_value)
    drawdown = (total_value - peak) / peak * 100 if peak else 0.0

    open_pos = db.query(PaperTrade).filter_by(
        portfolio_name=PORTFOLIO_NAME, is_open=True
    ).count()

    existing = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name=PORTFOLIO_NAME, date=today)
        .first()
    )
    if existing:
        existing.total_value          = total_value
        existing.cash                 = cash
        existing.invested             = invested
        existing.daily_return_pct     = round(daily_ret, 6)
        existing.cumulative_return_pct = round(cum_ret, 6)
        existing.drawdown_pct         = round(drawdown, 6)
        existing.open_positions       = open_pos
        existing.nifty_close          = nifty_close
        point = existing
    else:
        point = EquityCurvePoint(
            portfolio_name        = PORTFOLIO_NAME,
            date                  = today,
            total_value           = total_value,
            cash                  = cash,
            invested              = invested,
            daily_return_pct      = round(daily_ret, 6),
            cumulative_return_pct = round(cum_ret, 6),
            drawdown_pct          = round(drawdown, 6),
            open_positions        = open_pos,
            nifty_close           = nifty_close,
        )
        db.add(point)

    db.commit()
    return point


def _sharpe(returns: np.ndarray) -> float:
    if len(returns) < 5 or returns.std() == 0:
        return 0.0
    excess = returns - (RISK_FREE_RATE / TRADING_DAYS)
    return float(excess.mean() / excess.std() * math.sqrt(TRADING_DAYS))


def _sortino(returns: np.ndarray) -> float:
    if len(returns) < 5:
        return 0.0
    excess    = returns - (RISK_FREE_RATE / TRADING_DAYS)
    downside  = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(excess.mean() / downside.std() * math.sqrt(TRADING_DAYS))


def _cagr(initial: float, final: float, days: int) -> float:
    if days < 1 or initial <= 0:
        return 0.0
    years = days / 365.25
    return ((final / initial) ** (1 / years) - 1) * 100


def compute_and_save_snapshot(db: Session) -> PerformanceSnapshot:
    """
    Compute all performance metrics from equity curve + trade history,
    then upsert today's PerformanceSnapshot row.
    """
    today = date.today()

    # ── Equity curve ─────────────────────────────────────────────
    curve = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .order_by(EquityCurvePoint.date.asc())
        .all()
    )
    daily_rets  = np.array([p.daily_return_pct / 100 for p in curve if p.daily_return_pct is not None])
    total_days  = (curve[-1].date - curve[0].date).days if len(curve) > 1 else 0
    initial_val = curve[0].total_value if curve else 0
    final_val   = curve[-1].total_value if curve else 0
    total_ret   = (final_val - initial_val) / initial_val * 100 if initial_val else 0.0
    cagr        = _cagr(initial_val, final_val, total_days)
    sharpe      = _sharpe(daily_rets)
    sortino     = _sortino(daily_rets)
    vol_ann     = float(daily_rets.std() * math.sqrt(TRADING_DAYS) * 100) if len(daily_rets) > 1 else 0.0
    max_dd      = float(min((p.drawdown_pct or 0) for p in curve)) if curve else 0.0
    cur_dd      = float(curve[-1].drawdown_pct or 0) if curve else 0.0
    avg_exp     = float(np.mean([
        p.invested / p.total_value * 100 for p in curve
        if p.total_value and p.invested is not None
    ])) if curve else 0.0

    # ── Closed trades ─────────────────────────────────────────────
    closed = (
        db.query(PaperTrade)
        .filter_by(portfolio_name=PORTFOLIO_NAME, is_open=False)
        .all()
    )
    open_cnt   = db.query(PaperTrade).filter_by(portfolio_name=PORTFOLIO_NAME, is_open=True).count()
    total_trd  = len(closed) + open_cnt
    wins       = [t for t in closed if (t.gross_pnl or 0) > 0]
    losses     = [t for t in closed if (t.gross_pnl or 0) <= 0]
    win_rate   = len(wins) / len(closed) * 100 if closed else 0.0
    gross_win  = sum(t.gross_pnl or 0 for t in wins)
    gross_loss = abs(sum(t.gross_pnl or 0 for t in losses))
    if gross_loss > 0:
        if gross_win > 0:
            pf = gross_win / gross_loss
        else:
            pf = -gross_loss
    else:
        pf = 1.0 if gross_win > 0 else 0.0
    avg_win    = (sum(t.gross_pnl_pct or 0 for t in wins) / len(wins)) if wins else 0.0
    avg_loss   = (sum(t.gross_pnl_pct or 0 for t in losses) / len(losses)) if losses else 0.0
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)
    avg_hold   = (sum(t.holding_days or 0 for t in closed) / len(closed)) if closed else 0.0

    # Turnover: total capital deployed in closed trades / avg portfolio value
    avg_port   = float(np.mean([p.total_value for p in curve])) if curve else (initial_val or 1)
    cap_rotated = sum(t.capital_deployed for t in closed)
    turnover   = cap_rotated / avg_port * 100 if avg_port else 0.0

    existing = (
        db.query(PerformanceSnapshot)
        .filter_by(portfolio_name=PORTFOLIO_NAME, date=today)
        .first()
    )
    fields = dict(
        total_return_pct     = round(total_ret, 4),
        cagr_pct             = round(cagr, 4),
        daily_return_avg     = round(float(daily_rets.mean() * 100) if len(daily_rets) > 0 else 0.0, 6),
        sharpe_ratio         = round(sharpe, 4),
        sortino_ratio        = round(sortino, 4),
        max_drawdown_pct     = round(max_dd, 4),
        current_drawdown_pct = round(cur_dd, 4),
        volatility_ann       = round(vol_ann, 4),
        total_trades         = total_trd,
        open_trades          = open_cnt,
        closed_trades        = len(closed),
        winning_trades       = len(wins),
        losing_trades        = len(losses),
        win_rate_pct         = round(win_rate, 4),
        profit_factor        = round(pf, 4),
        expectancy_pct       = round(expectancy, 4),
        avg_win_pct          = round(avg_win, 4),
        avg_loss_pct         = round(avg_loss, 4),
        avg_holding_days     = round(avg_hold, 2),
        avg_exposure_pct     = round(avg_exp, 4),
        turnover_pct         = round(turnover, 4),
    )

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        snap = existing
    else:
        snap = PerformanceSnapshot(portfolio_name=PORTFOLIO_NAME, date=today, **fields)
        db.add(snap)

    db.commit()
    log.info(
        "Performance snapshot: ret=%.2f%%  sharpe=%.2f  sortino=%.2f  win=%.1f%%  pf=%.2f",
        total_ret, sharpe, sortino, win_rate, pf,
    )
    return snap


def get_equity_curve_data(db: Session, days: int = 90) -> dict:
    """Return equity curve as chart-ready arrays."""
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .filter(EquityCurvePoint.date >= cutoff)
        .order_by(EquityCurvePoint.date.asc())
        .all()
    )
    if not rows:
        return {"labels": [], "values": [], "drawdown": [], "dailyReturns": []}
    return {
        "labels":       [str(r.date) for r in rows],
        "values":       [round(r.total_value, 2) for r in rows],
        "drawdown":     [round(r.drawdown_pct or 0, 4) for r in rows],
        "dailyReturns": [round(r.daily_return_pct or 0, 4) for r in rows],
        "cash":         [round(r.cash, 2) for r in rows],
    }


def get_latest_snapshot(db: Session) -> Optional[dict]:
    """Return the most recent PerformanceSnapshot as a dict."""
    snap = (
        db.query(PerformanceSnapshot)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .order_by(PerformanceSnapshot.date.desc())
        .first()
    )
    if not snap:
        return None
    return {
        "date":              str(snap.date),
        "totalReturnPct":    snap.total_return_pct,
        "cagrPct":           snap.cagr_pct,
        "sharpeRatio":       snap.sharpe_ratio,
        "sortinoRatio":      snap.sortino_ratio,
        "maxDrawdownPct":    snap.max_drawdown_pct,
        "currentDrawdownPct": snap.current_drawdown_pct,
        "volatilityAnn":     snap.volatility_ann,
        "totalTrades":       snap.total_trades,
        "openTrades":        snap.open_trades,
        "closedTrades":      snap.closed_trades,
        "winningTrades":     snap.winning_trades,
        "losingTrades":      snap.losing_trades,
        "winRatePct":        snap.win_rate_pct,
        "profitFactor":      snap.profit_factor,
        "expectancyPct":     snap.expectancy_pct,
        "avgWinPct":         snap.avg_win_pct,
        "avgLossPct":        snap.avg_loss_pct,
        "avgHoldingDays":    snap.avg_holding_days,
        "avgExposurePct":    snap.avg_exposure_pct,
        "turnoverPct":       snap.turnover_pct,
    }

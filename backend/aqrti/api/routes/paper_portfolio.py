"""
Paper Portfolio API
GET /api/v1/paper-portfolio          — portfolio summary + open positions
GET /api/v1/paper-portfolio/positions — open positions with live P&L
GET /api/v1/paper-portfolio/allocation — current allocation view
"""

from __future__ import annotations

import sys
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.utils.logger import get_logger

log    = APIRouter()
router = log  # alias — FastAPI uses router


def _ensure_path():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


@router.get("")
def get_paper_portfolio(db: Session = Depends(get_db_dependency)):
    _ensure_path()
    from paper_trading.paper_portfolio import get_portfolio_summary
    from paper_trading.paper_trade import get_open_positions
    from paper_trading.performance_tracker import get_latest_snapshot

    summary   = get_portfolio_summary(db)
    positions = get_open_positions(db)
    snap      = get_latest_snapshot(db)

    return {
        "portfolio":  summary,
        "positions":  positions,
        "performance": snap or {},
        "available":  True,
    }


@router.get("/positions")
def get_positions(db: Session = Depends(get_db_dependency)):
    _ensure_path()
    from paper_trading.paper_trade import get_open_positions
    return get_open_positions(db)


@router.get("/equity-curve")
def get_equity_curve_endpoint(
    days: int = Query(default=90, ge=7, le=365),
    db:   Session = Depends(get_db_dependency),
):
    """
    Return equity curve.  If EquityCurvePoint has fewer than 3 rows,
    reconstruct a synthetic curve from paper trade history so the
    chart always shows something meaningful.
    """
    _ensure_path()
    from paper_trading.performance_tracker import get_equity_curve_data
    from aqrti.database.models import EquityCurvePoint, PaperTrade, PaperPortfolio
    from aqrti.config.settings import get_settings
    from datetime import date, timedelta
    from collections import defaultdict

    data = get_equity_curve_data(db, days=days)
    if len(data.get("labels", [])) >= 3:
        return data

    # ── Synthetic reconstruction from paper trade history ──────────
    settings  = get_settings()
    paper     = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    capital   = paper.initial_capital if paper else settings.paper_capital
    end_val   = paper.total_value if paper else capital

    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_name == "default")
        .all()
    )
    if not trades:
        return data  # nothing to reconstruct from

    # Build daily net PnL from closed trades
    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if not t.is_open and t.gross_pnl and t.exit_date:
            daily_pnl[str(t.exit_date)] += t.gross_pnl

    sorted_dates = sorted(daily_pnl.keys())
    if not sorted_dates:
        return data

    # Walk forward from capital, filling every calendar day
    cutoff    = date.today() - timedelta(days=days)
    running   = capital
    labels, values, drawdown_vals, daily_ret_vals = [], [], [], []
    peak      = capital

    # Start one day before first trade date
    first_trade_d = date.fromisoformat(sorted_dates[0])
    start_d = max(cutoff, first_trade_d - timedelta(days=1))
    cur_d   = start_d

    while cur_d <= date.today():
        pnl   = daily_pnl.get(str(cur_d), 0.0)
        prev  = running
        running += pnl
        daily_r = (running - prev) / prev * 100 if prev else 0.0
        peak    = max(peak, running)
        dd      = (running - peak) / peak * 100 if peak else 0.0

        labels.append(str(cur_d))
        values.append(round(running, 2))
        drawdown_vals.append(round(dd, 4))
        daily_ret_vals.append(round(daily_r, 4))
        cur_d += timedelta(days=1)

    return {
        "labels":       labels,
        "values":       values,
        "drawdown":     drawdown_vals,
        "dailyReturns": daily_ret_vals,
        "cash":         [],
        "source":       "reconstructed",
    }


@router.post("/backfill-equity")
def backfill_equity_curve(db: Session = Depends(get_db_dependency)):
    """
    One-time backfill: create EquityCurvePoint rows from paper trade history
    so performance_tracker has real historical data to compute metrics from.
    """
    _ensure_path()
    from aqrti.database.models import EquityCurvePoint, PaperTrade, PaperPortfolio
    from aqrti.config.settings import get_settings
    from datetime import date, timedelta
    from collections import defaultdict

    settings = get_settings()
    paper    = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    capital  = paper.initial_capital if paper else settings.paper_capital

    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_name == "default")
        .all()
    )
    if not trades:
        return {"message": "No paper trades found — nothing to backfill", "inserted": 0}

    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if not t.is_open and t.gross_pnl and t.exit_date:
            daily_pnl[str(t.exit_date)] += t.gross_pnl

    if not daily_pnl:
        return {"message": "No closed trades with P&L — nothing to backfill", "inserted": 0}

    sorted_dates = sorted(daily_pnl.keys())
    first_d = date.fromisoformat(sorted_dates[0])
    start_d = first_d - timedelta(days=1)

    running  = capital
    peak     = capital
    inserted = 0

    cur_d = start_d
    while cur_d <= date.today():
        existing = (
            db.query(EquityCurvePoint)
            .filter_by(portfolio_name="default", date=cur_d)
            .first()
        )
        if not existing:
            pnl     = daily_pnl.get(str(cur_d), 0.0)
            prev    = running
            running += pnl
            daily_r = (running - prev) / prev * 100 if prev else 0.0
            peak    = max(peak, running)
            dd      = (running - peak) / peak * 100 if peak else 0.0
            cum_r   = (running - capital) / capital * 100 if capital else 0.0

            db.add(EquityCurvePoint(
                portfolio_name        = "default",
                date                  = cur_d,
                total_value           = round(running, 2),
                cash                  = round(running, 2),
                invested              = 0.0,
                daily_return_pct      = round(daily_r, 6),
                cumulative_return_pct = round(cum_r, 6),
                drawdown_pct          = round(dd, 6),
                open_positions        = 0,
                nifty_close           = None,
            ))
            inserted += 1
        else:
            pnl     = daily_pnl.get(str(cur_d), 0.0)
            running += pnl
            peak    = max(peak, running)

        cur_d += timedelta(days=1)

    db.commit()
    return {"message": f"Backfilled {inserted} equity curve points", "inserted": inserted}


@router.get("/allocation")
def get_allocation(
    method:  str = Query(default="confidence_weighted"),
    db: Session = Depends(get_db_dependency),
):
    _ensure_path()
    from portfolio.portfolio_builder import get_allocation_view
    return get_allocation_view(db, method=method)

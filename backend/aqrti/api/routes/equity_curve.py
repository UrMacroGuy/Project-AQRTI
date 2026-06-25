"""
Equity Curve API
GET /api/v1/equity-curve           — chart-ready equity curve data
GET /api/v1/equity-curve/raw       — raw rows for custom rendering
"""

from __future__ import annotations

import sys
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


def _ensure_path():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


@router.get("")
def get_equity_curve(
    days: int = Query(default=90, le=365),
    db:   Session = Depends(get_db_dependency),
):
    """
    Return equity curve — tries EquityCurvePoint rows first,
    reconstructs from paper trade P&L history when sparse.
    """
    _ensure_path()
    from paper_trading.performance_tracker import get_equity_curve_data
    from aqrti.database.models import PaperPortfolio, PaperTrade, EquityCurvePoint
    from aqrti.config.settings import get_settings
    from datetime import date, timedelta
    from collections import defaultdict

    data = get_equity_curve_data(db, days=days)
    if len(data.get("labels", [])) >= 3:
        return data

    # Reconstruct from closed paper trade P&L
    settings = get_settings()
    paper    = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    capital  = paper.initial_capital if paper else settings.paper_capital

    trades = db.query(PaperTrade).filter(PaperTrade.portfolio_name == "default").all()
    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if not t.is_open and t.gross_pnl and t.exit_date:
            daily_pnl[str(t.exit_date)] += t.gross_pnl

    if not daily_pnl:
        return data

    cutoff      = date.today() - timedelta(days=days)
    sorted_keys = sorted(daily_pnl.keys())
    start_d     = date.fromisoformat(sorted_keys[0]) - timedelta(days=1)
    running     = capital
    peak        = capital
    labels, values, drawdown_out, daily_ret_out = [], [], [], []

    cur_d = start_d
    while cur_d <= date.today():
        pnl   = daily_pnl.get(str(cur_d), 0.0)
        prev  = running
        running += pnl
        daily_r = (running - prev) / prev * 100 if prev else 0.0
        peak    = max(peak, running)
        dd      = (running - peak) / peak * 100 if peak else 0.0

        if cur_d >= cutoff:
            labels.append(str(cur_d))
            values.append(round(running, 2))
            drawdown_out.append(round(dd, 4))
            daily_ret_out.append(round(daily_r, 4))
        cur_d += timedelta(days=1)

    return {
        "labels":       labels,
        "values":       values,
        "drawdown":     drawdown_out,
        "dailyReturns": daily_ret_out,
        "cash":         [],
        "source":       "reconstructed",
    }


@router.get("/raw")
def get_equity_curve_raw(
    days: int = Query(default=90, le=365),
    db:   Session = Depends(get_db_dependency),
):
    """Return raw EquityCurvePoint rows as list of dicts."""
    from datetime import date, timedelta
    from aqrti.database.models import EquityCurvePoint
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name="default")
        .filter(EquityCurvePoint.date >= cutoff)
        .order_by(EquityCurvePoint.date.asc())
        .all()
    )
    return [
        {
            "date":               str(r.date),
            "totalValue":         r.total_value,
            "cash":               r.cash,
            "invested":           r.invested,
            "dailyReturnPct":     r.daily_return_pct,
            "cumulativeReturnPct": r.cumulative_return_pct,
            "drawdownPct":        r.drawdown_pct,
            "openPositions":      r.open_positions,
            "niftyClose":         r.nifty_close,
        }
        for r in rows
    ]

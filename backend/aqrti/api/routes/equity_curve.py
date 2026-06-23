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
    """Return equity curve as chart-ready arrays (labels + values)."""
    _ensure_path()
    from paper_trading.performance_tracker import get_equity_curve_data
    return get_equity_curve_data(db, days=days)


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

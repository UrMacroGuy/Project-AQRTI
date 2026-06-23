"""
Performance Analytics API
GET /api/v1/performance          — latest performance snapshot (all metrics)
GET /api/v1/performance/history  — snapshot history over time
GET /api/v1/performance/summary  — condensed KPI summary for overview panels
"""

from __future__ import annotations

import sys
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import PerformanceSnapshot

router = APIRouter()

PORTFOLIO_NAME = "default"


def _ensure_path():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


@router.get("")
def get_performance(db: Session = Depends(get_db_dependency)):
    _ensure_path()
    from paper_trading.performance_tracker import get_latest_snapshot
    snap = get_latest_snapshot(db)
    if not snap:
        return {"available": False}
    snap["available"] = True
    return snap


@router.get("/summary")
def get_performance_summary(db: Session = Depends(get_db_dependency)):
    """Condensed KPIs for the Overview and Risk pages."""
    _ensure_path()
    from paper_trading.performance_tracker import get_latest_snapshot
    from paper_trading.paper_portfolio import get_portfolio_summary

    snap = get_latest_snapshot(db)
    port = get_portfolio_summary(db)

    return {
        "available":       snap is not None,
        "portfolioValue":  port["totalValue"],
        "totalReturnPct":  snap["totalReturnPct"] if snap else 0.0,
        "cagrPct":         snap["cagrPct"] if snap else 0.0,
        "sharpeRatio":     snap["sharpeRatio"] if snap else 0.0,
        "sortinoRatio":    snap["sortinoRatio"] if snap else 0.0,
        "maxDrawdownPct":  snap["maxDrawdownPct"] if snap else 0.0,
        "winRatePct":      snap["winRatePct"] if snap else 0.0,
        "profitFactor":    snap["profitFactor"] if snap else 0.0,
        "openPositions":   port["totalValue"] - port["currentCash"],
        "cashPct":         port["cashPct"],
    }


@router.get("/history")
def get_performance_history(
    days: int = Query(default=90, le=365),
    db:   Session = Depends(get_db_dependency),
):
    """Return PerformanceSnapshot rows for trend charts."""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(PerformanceSnapshot)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .filter(PerformanceSnapshot.date >= cutoff)
        .order_by(PerformanceSnapshot.date.asc())
        .all()
    )
    return [
        {
            "date":           str(r.date),
            "totalReturnPct": r.total_return_pct,
            "sharpeRatio":    r.sharpe_ratio,
            "maxDrawdownPct": r.max_drawdown_pct,
            "winRatePct":     r.win_rate_pct,
            "profitFactor":   r.profit_factor,
            "openTrades":     r.open_trades,
            "closedTrades":   r.closed_trades,
        }
        for r in rows
    ]

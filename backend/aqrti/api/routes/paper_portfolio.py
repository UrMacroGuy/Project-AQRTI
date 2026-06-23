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


@router.get("/allocation")
def get_allocation(
    method:  str = Query(default="confidence_weighted"),
    db: Session = Depends(get_db_dependency),
):
    _ensure_path()
    from portfolio.portfolio_builder import get_allocation_view
    return get_allocation_view(db, method=method)

"""
Rebalance API
GET  /api/v1/rebalance          — preview next rebalance (no execution)
POST /api/v1/rebalance/execute  — execute rebalance immediately
"""

from __future__ import annotations

import sys
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.utils.logger import get_logger

log    = get_logger("rebalance_route")
router = APIRouter()


def _ensure_path():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


@router.get("")
def preview_rebalance(
    method:  str = Query(default="confidence_weighted"),
    db: Session = Depends(get_db_dependency),
):
    """
    Preview the rebalance that would happen if triggered now.
    Does NOT execute any trades.
    """
    _ensure_path()
    from portfolio.rebalancer import get_rebalance_preview
    return get_rebalance_preview(db)


@router.post("/execute")
def execute_rebalance(
    reason: str = Query(default="manual_rebalance"),
    db: Session = Depends(get_db_dependency),
):
    """
    Execute a full rebalance cycle right now.
    Equivalent to one iteration of the daily paper trading cycle.
    """
    _ensure_path()
    from paper_trading.paper_engine import run_paper_trading_cycle
    log.info("Manual rebalance triggered via API")
    return run_paper_trading_cycle()

"""
Paper Trades API
GET /api/v1/paper-trades              — closed trade history
GET /api/v1/paper-trades/symbol/{sym} — trades for one symbol
GET /api/v1/paper-trades/stats        — aggregate trade stats
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
def get_trades(
    limit:  int = Query(default=100, le=500),
    db: Session = Depends(get_db_dependency),
):
    _ensure_path()
    from paper_trading.paper_trade import get_trade_history
    return get_trade_history(db, limit=limit)


@router.get("/stats")
def get_trade_stats(db: Session = Depends(get_db_dependency)):
    _ensure_path()
    from paper_trading.performance_tracker import get_latest_snapshot
    snap = get_latest_snapshot(db)
    if not snap:
        return {"available": False}
    return {
        "available":     True,
        "totalTrades":   snap["totalTrades"],
        "closedTrades":  snap["closedTrades"],
        "openTrades":    snap["openTrades"],
        "winningTrades": snap["winningTrades"],
        "losingTrades":  snap["losingTrades"],
        "winRatePct":    snap["winRatePct"],
        "profitFactor":  snap["profitFactor"],
        "expectancyPct": snap["expectancyPct"],
        "avgWinPct":     snap["avgWinPct"],
        "avgLossPct":    snap["avgLossPct"],
        "avgHoldingDays":snap["avgHoldingDays"],
    }


@router.get("/symbol/{symbol}")
def get_symbol_trades(
    symbol: str,
    limit:  int = Query(default=50, le=200),
    db: Session = Depends(get_db_dependency),
):
    _ensure_path()
    from paper_trading.paper_trade import get_trade_history
    return get_trade_history(db, limit=limit, symbol=symbol.upper())

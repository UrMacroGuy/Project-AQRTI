"""Knowledge API — /api/v1/knowledge"""

from __future__ import annotations

import sys, os
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("")
def get_knowledge_overview(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    from learning.knowledge_store import get_recent_events, get_event_counts
    from learning.knowledge_score import get_latest_score, get_score_history
    events = get_recent_events(db, days=days)
    counts = get_event_counts(db, days=days)
    score  = get_latest_score(db)
    hist   = get_score_history(db, days=min(days, 90))
    return {
        "currentScore":   score,
        "scoreHistory":   hist,
        "recentEvents":   events,
        "eventCounts":    counts,
        "days":           days,
    }


@router.get("/graph/symbol/{symbol}")
def get_symbol_knowledge(
    symbol: str,
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    from learning.knowledge_graph import build_symbol_graph
    return build_symbol_graph(db, symbol=symbol, days=days)


@router.get("/graph/market")
def get_market_knowledge(
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db_dependency),
):
    from learning.knowledge_graph import build_market_graph
    return build_market_graph(db, days=days)


@router.get("/score/history")
def get_score_history_route(
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    from learning.knowledge_score import get_score_history
    return {"history": get_score_history(db, days=days), "days": days}

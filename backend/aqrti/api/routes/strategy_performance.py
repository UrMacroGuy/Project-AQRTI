"""Strategy Performance API — /api/v1/strategy-performance"""

from __future__ import annotations

import sys, os, json

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import StrategyPerformance, StrategyV2
from strategies.strategy_metrics import live_performance_metrics

router = APIRouter()


@router.get("")
def list_performance(
    strategy_id: str | None = Query(default=None),
    days:        int        = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(StrategyPerformance).filter(StrategyPerformance.date >= cutoff)
    if strategy_id:
        q = q.filter(StrategyPerformance.strategy_id == strategy_id)
    rows = q.order_by(StrategyPerformance.date.desc()).limit(500).all()

    return {
        "performance": [
            {
                "strategy_id":    r.strategy_id,
                "date":           str(r.date),
                "signals_fired":  r.signals_fired,
                "trades_opened":  r.trades_opened,
                "trades_closed":  r.trades_closed,
                "daily_pnl":      r.daily_pnl,
                "daily_pnl_pct":  r.daily_pnl_pct,
                "cumulative_pnl": r.cumulative_pnl,
                "win_count":      r.win_count,
                "loss_count":     r.loss_count,
                "regime_at":      r.regime_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/{strategy_id}/metrics")
def get_live_metrics(
    strategy_id: str,
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return live_performance_metrics(db, strategy_id, days=days)


@router.get("/{strategy_id}/chart")
def get_pnl_chart(
    strategy_id: str,
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(StrategyPerformance)
        .filter(
            StrategyPerformance.strategy_id == strategy_id,
            StrategyPerformance.date >= cutoff,
        )
        .order_by(StrategyPerformance.date)
        .all()
    )
    return {
        "strategy_id": strategy_id,
        "labels":      [str(r.date) for r in rows],
        "cumulative_pnl": [r.cumulative_pnl for r in rows],
        "daily_pnl_pct":  [r.daily_pnl_pct for r in rows],
        "regime":         [r.regime_at for r in rows],
    }

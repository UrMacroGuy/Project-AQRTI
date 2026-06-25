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
    from sqlalchemy import func, case
    from aqrti.database.models import StrategyBacktestTrade

    cutoff = date.today() - timedelta(days=days)

    # Try StrategyPerformance table first (live trading records)
    q = db.query(StrategyPerformance).filter(StrategyPerformance.date >= cutoff)
    if strategy_id:
        q = q.filter(StrategyPerformance.strategy_id == strategy_id)
    rows = q.order_by(StrategyPerformance.date.desc()).limit(500).all()

    if rows:
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
            "source": "live",
        }

    # Fall back: aggregate stats from strategy_backtest_trades
    bt_q = (
        db.query(
            StrategyBacktestTrade.strategy_id,
            func.count(StrategyBacktestTrade.id).label("tc"),
            func.avg(StrategyBacktestTrade.pnl_pct).label("avg_pnl"),
            func.sum(StrategyBacktestTrade.pnl_pct).label("total_pnl"),
            func.sum(case((StrategyBacktestTrade.pnl_pct > 0, 1), else_=0)).label("wins"),
        )
        .group_by(StrategyBacktestTrade.strategy_id)
        .order_by(func.count(StrategyBacktestTrade.id).desc())
        .limit(50)
    )
    if strategy_id:
        bt_q = bt_q.filter(StrategyBacktestTrade.strategy_id == strategy_id)
    bt_rows = bt_q.all()

    # Enrich with strategy names
    sid_list = [r.strategy_id for r in bt_rows]
    strat_map = {
        s.strategy_id: s.name
        for s in db.query(StrategyV2).filter(StrategyV2.strategy_id.in_(sid_list)).all()
    }

    perf = []
    for r in bt_rows:
        tc = r.tc or 0
        wins = r.wins or 0
        losses = tc - wins
        avg_pnl = round(r.avg_pnl or 0, 4)
        total_pnl = round(r.total_pnl or 0, 4)
        wr = round(wins * 100.0 / tc, 1) if tc > 0 else 0.0
        perf.append({
            "strategy_id":    r.strategy_id,
            "name":           strat_map.get(r.strategy_id, r.strategy_id),
            "date":           str(date.today()),
            "trade_count":    tc,
            "win_count":      wins,
            "loss_count":     losses,
            "win_rate":       wr,
            "avg_pnl_pct":    avg_pnl,
            "total_pnl_pct":  total_pnl,
            "source":         "backtest",
        })

    return {"performance": perf, "total": len(perf), "source": "backtest"}


@router.post("/validate")
def run_validation_sweep(
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    """
    Full live-vs-backtest validation sweep.
    Reads all closed paper trades, writes StrategyPerformance rows,
    demotes strategies that diverge badly from their backtest metrics.
    """
    from strategies.live_validator import run_daily_validation_sweep
    return run_daily_validation_sweep(db, days_back=days)


@router.get("/{strategy_id}/validation")
def get_strategy_validation(
    strategy_id: str,
    db: Session = Depends(get_db_dependency),
):
    """Live-vs-backtest comparison for one strategy (used by DNA viewer)."""
    from strategies.live_validator import get_live_validation_summary
    return get_live_validation_summary(db, strategy_id)


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

    # Try live StrategyPerformance rows first
    rows = (
        db.query(StrategyPerformance)
        .filter(
            StrategyPerformance.strategy_id == strategy_id,
            StrategyPerformance.date >= cutoff,
        )
        .order_by(StrategyPerformance.date)
        .all()
    )
    if rows:
        return {
            "strategy_id":    strategy_id,
            "labels":         [str(r.date) for r in rows],
            "cumulative_pnl": [r.cumulative_pnl for r in rows],
            "daily_pnl_pct":  [r.daily_pnl_pct for r in rows],
            "regime":         [r.regime_at for r in rows],
        }

    # Build synthetic equity curve from backtest trades
    from aqrti.database.models import StrategyBacktestTrade
    trades = (
        db.query(StrategyBacktestTrade)
        .filter(
            StrategyBacktestTrade.strategy_id == strategy_id,
            StrategyBacktestTrade.exit_date != None,
        )
        .order_by(StrategyBacktestTrade.exit_date.asc())
        .all()
    )
    if not trades:
        return {"strategy_id": strategy_id, "labels": [], "cumulative_pnl": [], "daily_pnl_pct": [], "regime": []}

    # Group by exit date, accumulate cumulative P&L
    from collections import defaultdict
    daily_pnl: dict = defaultdict(float)
    for t in trades:
        d = str(t.exit_date)
        daily_pnl[d] += (t.pnl_pct or 0.0)

    sorted_dates = sorted(daily_pnl.keys())
    cum = 0.0
    labels, cum_pnl, daily = [], [], []
    for d in sorted_dates:
        pnl = round(daily_pnl[d], 4)
        cum = round(cum + pnl, 4)
        labels.append(d)
        daily.append(pnl)
        cum_pnl.append(cum)

    return {
        "strategy_id":    strategy_id,
        "labels":         labels,
        "cumulative_pnl": cum_pnl,
        "daily_pnl_pct":  daily,
        "regime":         [],
        "source":         "backtest",
    }

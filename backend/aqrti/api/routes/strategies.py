"""Strategy API — /api/v1/strategies (Phase 6 — StrategyV2)"""

from __future__ import annotations

import sys, os, json

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from strategies.strategy_store import (
    get_strategy, list_strategies, get_population_stats,
)
from strategies.strategy_registry import (
    get_leaderboard, get_family_summary, count_by_generation,
)
from strategies.strategy_lifecycle import (
    promote_strategy, retire_strategy, run_lifecycle_sweep,
)
from strategies.strategy_generator import run_generation_cycle
from strategies.evolution_engine import evolve_population

router = APIRouter()


def _safe_json(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return s


@router.get("")
def get_strategies(
    status:   str | None = Query(default=None),
    family:   str | None = Query(default=None),
    limit:    int        = Query(default=50, ge=1, le=200),
    order_by: str        = Query(default="fitness_score"),
    db: Session = Depends(get_db_dependency),
):
    rows = list_strategies(db, status=status, family=family, limit=limit, order_by=order_by)
    return {
        "strategies": [
            {
                "strategy_id":    r.strategy_id,
                "name":           r.name,
                "family":         r.family,
                "generation":     r.generation,
                "status":         r.status,
                "fitness_score":  r.fitness_score,
                "sharpe":         r.sharpe,
                "win_rate":       r.win_rate,
                "profit_factor":  r.profit_factor,
                "max_drawdown":   r.max_drawdown,
                "trade_count":    r.trade_count,
                "allowed_regimes": _safe_json(r.allowed_regimes),
                "created_at":     r.created_at.isoformat() if r.created_at else None,
                "promoted_at":    r.promoted_at.isoformat() if r.promoted_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/population")
def get_population(db: Session = Depends(get_db_dependency)):
    return {
        "stats":         get_population_stats(db),
        "by_family":     get_family_summary(db),
        "by_generation": count_by_generation(db),
        "leaderboard":   get_leaderboard(db, top_n=10),
    }


@router.get("/leaderboard")
def get_leaderboard_endpoint(
    top_n:  int        = Query(default=20, ge=5, le=100),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db_dependency),
):
    return {"leaderboard": get_leaderboard(db, top_n=top_n, status=status)}


@router.get("/{strategy_id}")
def get_strategy_detail(strategy_id: str, db: Session = Depends(get_db_dependency)):
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {
        "strategy_id":      row.strategy_id,
        "name":             row.name,
        "family":           row.family,
        "generation":       row.generation,
        "status":           row.status,
        "status_reason":    row.status_reason,
        "fitness_score":    row.fitness_score,
        "sharpe":           row.sharpe,
        "sortino":          row.sortino,
        "win_rate":         row.win_rate,
        "profit_factor":    row.profit_factor,
        "max_drawdown":     row.max_drawdown,
        "expectancy":       row.expectancy,
        "trade_count":      row.trade_count,
        "avg_holding_days": row.avg_holding_days,
        "exposure_pct":     row.exposure_pct,
        "bull_sharpe":      row.bull_sharpe,
        "bear_sharpe":      row.bear_sharpe,
        "sideways_sharpe":  row.sideways_sharpe,
        "volatile_sharpe":  row.volatile_sharpe,
        "backtest_start":   str(row.backtest_start) if row.backtest_start else None,
        "backtest_end":     str(row.backtest_end) if row.backtest_end else None,
        "allowed_regimes":  _safe_json(row.allowed_regimes),
        "feature_categories": _safe_json(row.feature_categories),
        "parent_ids":       _safe_json(row.parent_ids),
        "dsl":              _safe_json(row.dsl_json),
        "promoted_at":      row.promoted_at.isoformat() if row.promoted_at else None,
        "retired_at":       row.retired_at.isoformat() if row.retired_at else None,
        "created_at":       row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/{strategy_id}/promote")
def promote(
    strategy_id: str,
    reason: str = Query(default="manual_approval"),
    db: Session = Depends(get_db_dependency),
):
    result = promote_strategy(db, strategy_id, reason=reason)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{strategy_id}/activate")
def activate(strategy_id: str, db: Session = Depends(get_db_dependency)):
    """Human approval — moves 'promoted' → 'active'. No automatic path exists."""
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if row.status != "promoted":
        raise HTTPException(
            status_code=400,
            detail=f"Strategy must be in 'promoted' state to activate. Current: {row.status}",
        )
    row.status        = "active"
    row.status_reason = "human_approved"
    db.commit()
    return {"strategy_id": strategy_id, "status": "active", "message": "Strategy activated by human approval"}


@router.post("/{strategy_id}/retire")
def retire(
    strategy_id: str,
    reason: str = Query(default="manual_retirement"),
    db: Session = Depends(get_db_dependency),
):
    result = retire_strategy(db, strategy_id, failure_reason=reason)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # 2-for-1 breeding: spawn 2 offspring to replace the retired strategy
    try:
        breed_result = evolve_population(db, n_offspring=2)
        result["bred_offspring"] = breed_result.get("evolved", 0)
        result["breed_message"] = f"Spawned {breed_result.get('evolved', 0)} new strategies to replace retired one"
    except Exception as exc:
        result["breed_error"] = str(exc)

    return result


@router.post("/admin/lifecycle-sweep")
def lifecycle_sweep(db: Session = Depends(get_db_dependency)):
    return run_lifecycle_sweep(db)


@router.post("/admin/generate")
def generate_candidates(
    n: int = Query(default=50, ge=10, le=200),
    db: Session = Depends(get_db_dependency),
):
    return run_generation_cycle(db, n=n, generation=0)


@router.post("/admin/evolve")
def evolve(
    n_offspring: int = Query(default=20, ge=5, le=100),
    db: Session = Depends(get_db_dependency),
):
    return evolve_population(db, n_offspring=n_offspring)


@router.get("/{strategy_id}/trades")
def get_strategy_trades(
    strategy_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    """Return individual backtest trades for a strategy."""
    from aqrti.database.models import StrategyBacktestTrade
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    trades = (
        db.query(StrategyBacktestTrade)
        .filter_by(strategy_id=strategy_id)
        .order_by(StrategyBacktestTrade.entry_date)
        .limit(limit)
        .all()
    )
    # Build cumulative equity curve from trades
    equity = 100.0
    equity_curve = []
    for t in trades:
        pnl = t.pnl_pct or 0.0
        equity *= (1 + pnl / 100)
        equity_curve.append(round(equity, 4))

    return {
        "strategy_id": strategy_id,
        "name":        row.name,
        "family":      row.family,
        "status":      row.status,
        "fitness":     row.fitness_score,
        "sharpe":      row.sharpe,
        "win_rate":    row.win_rate,
        "trade_count": len(trades),
        "trades": [
            {
                "symbol":      t.symbol,
                "entryDate":   str(t.entry_date),
                "exitDate":    str(t.exit_date) if t.exit_date else None,
                "entryPrice":  t.entry_price,
                "exitPrice":   t.exit_price,
                "pnlPct":      round(t.pnl_pct, 4) if t.pnl_pct else None,
                "exitReason":  t.exit_reason,
                "holdingDays": t.holding_days,
                "result":      "win" if (t.pnl_pct or 0) > 0 else "loss" if (t.pnl_pct or 0) < 0 else "flat",
            }
            for t in trades
        ],
        "equityCurve": equity_curve,
    }


@router.post("/{strategy_id}/replay")
def replay_strategy(
    strategy_id: str,
    db: Session = Depends(get_db_dependency),
):
    """Re-run backtest for a strategy and return full trade sequence for replay."""
    import json as _json
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if not row.dsl_json:
        raise HTTPException(status_code=400, detail="Strategy has no DSL definition")

    from strategies.strategy_backtester import backtest_and_update
    from strategies.strategy_dsl import StrategyDSL

    try:
        dsl = StrategyDSL.from_dict(_json.loads(row.dsl_json))
        result = backtest_and_update(db, dsl)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Build equity curve for replay animation
    equity = 100.0
    replay_frames = []
    for t in result.trades:
        pnl = t.pnl_pct or 0.0
        equity *= (1 + pnl / 100)
        replay_frames.append({
            "symbol":      t.symbol,
            "entryDate":   str(t.entry_date),
            "exitDate":    str(t.exit_date) if t.exit_date else None,
            "entryPrice":  t.entry_price,
            "exitPrice":   t.exit_price,
            "pnlPct":      round(t.pnl_pct, 4) if t.pnl_pct else None,
            "equityAfter": round(equity, 2),
            "result":      "win" if pnl > 0 else "loss" if pnl < 0 else "flat",
            "holdingDays": t.holding_days,
            "exitReason":  t.exit_reason,
        })

    return {
        "strategy_id":  strategy_id,
        "name":         row.name,
        "family":       row.family,
        "sharpe":       result.sharpe,
        "win_rate":     result.win_rate,
        "total_return": result.total_return,
        "trade_count":  result.trade_count,
        "max_drawdown": result.max_drawdown,
        "frames":       replay_frames,
        "finalEquity":  round(equity, 2),
    }

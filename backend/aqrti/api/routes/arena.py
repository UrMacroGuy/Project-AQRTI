"""
Strategy Arena API — /api/v1/arena
Exposes arena status, champion list, run history, and manual triggers.
"""

from __future__ import annotations

import json
import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import ArenaRun, StrategyV2

router = APIRouter()


@router.get("")
def get_arena_status(db: Session = Depends(get_db_dependency)):
    """Overall arena status — running, champions, refining counts."""
    from arena.arena_engine import get_arena_status
    return get_arena_status(db)


@router.get("/champions")
def get_champions(db: Session = Depends(get_db_dependency)):
    """All champion strategies — sorted by return descending."""
    runs = (
        db.query(ArenaRun)
        .filter_by(is_champion=True)
        .order_by(ArenaRun.total_return_pct.desc())
        .all()
    )
    results = []
    for r in runs:
        strat = db.query(StrategyV2).filter_by(strategy_id=r.strategy_id).first()
        results.append({
            "strategy_id":      r.strategy_id,
            "strategy_name":    r.strategy_name,
            "total_return_pct": r.total_return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "win_rate":         r.win_rate,
            "total_trades":     r.total_trades,
            "round_reached":    r.round_number,
            "generation":       r.generation,
            "completed_at":     str(r.completed_at) if r.completed_at else None,
            "fitness_score":    strat.fitness_score if strat else None,
            "dsl_json":         strat.dsl_json if strat else None,
        })
    return {"champions": results, "count": len(results)}


@router.get("/runs")
def get_runs(
    limit:  int = Query(default=50, ge=1, le=200),
    status: str = Query(default="all"),
    db: Session = Depends(get_db_dependency),
):
    """All arena runs — for the history table in the UI."""
    q = db.query(ArenaRun).order_by(ArenaRun.started_at.desc())
    if status != "all":
        q = q.filter(ArenaRun.status == status)
    runs = q.limit(limit).all()

    return {
        "runs": [
            {
                "id":                r.id,
                "strategy_id":       r.strategy_id,
                "strategy_name":     r.strategy_name,
                "round":             r.round_number,
                "generation":        r.generation,
                "status":            r.status,
                "total_return_pct":  r.total_return_pct,
                "max_drawdown_pct":  r.max_drawdown_pct,
                "win_rate":          r.win_rate,
                "total_trades":      r.total_trades,
                "winning_days":      r.winning_days_count,
                "losing_days":       r.losing_days_count,
                "passes_return":     r.passes_return_gate,
                "passes_drawdown":   r.passes_drawdown_gate,
                "passes_winrate":    r.passes_winrate_gate,
                "is_champion":       r.is_champion,
                "needs_review":      r.needs_review,
                "donor_name":        r.donor_strategy_name,
                "donor_coverage":    r.donor_coverage_pct,
                "started_at":        str(r.started_at) if r.started_at else None,
                "completed_at":      str(r.completed_at) if r.completed_at else None,
            }
            for r in runs
        ],
        "total": db.query(ArenaRun).count(),
    }


@router.get("/equity/{strategy_id}")
def get_equity_curve(
    strategy_id: str,
    db: Session = Depends(get_db_dependency),
):
    """Equity curve for a specific arena strategy (from daily_results_json)."""
    run = (
        db.query(ArenaRun)
        .filter_by(strategy_id=strategy_id)
        .order_by(ArenaRun.round_number.desc())
        .first()
    )
    if not run or not run.daily_results_json:
        return {"labels": [], "values": [], "strategy_id": strategy_id}

    try:
        daily = json.loads(run.daily_results_json)
    except Exception:
        return {"labels": [], "values": [], "strategy_id": strategy_id}

    labels = [d.get("date", "") for d in daily]
    values = []
    running = 100_000.0
    for d in daily:
        running += d.get("day_pnl", 0)
        values.append(round(running, 2))

    return {
        "strategy_id":      strategy_id,
        "strategy_name":    run.strategy_name,
        "labels":           labels,
        "values":           values,
        "total_return_pct": run.total_return_pct,
        "status":           run.status,
    }


@router.post("/run")
def trigger_arena(db: Session = Depends(get_db_dependency)):
    """Manually trigger the arena cycle (runs in background thread)."""
    from arena.arena_engine import run_arena_cycle
    result = run_arena_cycle()
    return result


@router.post("/promote")
def trigger_auto_promote(db: Session = Depends(get_db_dependency)):
    """Manually trigger auto-promotion of eligible strategies."""
    from arena.arena_engine import auto_promote_strategies
    activated = auto_promote_strategies(db)
    return {"activated": activated, "count": len(activated)}


@router.get("/needs-review")
def get_needs_review(db: Session = Depends(get_db_dependency)):
    """
    Strategies that failed to converge after MAX_ROUNDS — one row per
    strategy (its latest round), not one row per round. A strategy that
    exhausts all 10 rounds gets a needs_review=True ArenaRun row written for
    EVERY round (see arena_engine.run_arena_for_strategy's bulk .update()),
    so filtering on needs_review=True alone returned up to 10 duplicate rows
    per strategy — pick the highest round_number per strategy_id instead.
    """
    runs = (
        db.query(ArenaRun)
        .filter_by(needs_review=True)
        .order_by(ArenaRun.strategy_id, ArenaRun.round_number.desc())
        .all()
    )
    latest_by_strategy: dict[str, ArenaRun] = {}
    for r in runs:
        if r.strategy_id not in latest_by_strategy:
            latest_by_strategy[r.strategy_id] = r

    results = sorted(
        latest_by_strategy.values(),
        key=lambda r: r.total_return_pct or 0,
        reverse=True,
    )
    return {
        "strategies": [
            {
                "strategy_id":      r.strategy_id,
                "strategy_name":    r.strategy_name,
                "best_return_pct":  r.total_return_pct,
                "win_rate":         r.win_rate,
                "losing_days":      r.losing_days_count,
                "rounds_completed": r.round_number,
            }
            for r in results
        ],
        "count": len(results),
    }


@router.post("/needs-review/{strategy_id}/retry")
def retry_needs_review(strategy_id: str, db: Session = Depends(get_db_dependency)):
    """
    Give a needs_review strategy a fresh set of arena rounds. arena_engine's
    round counter (run_arena_for_strategy) counts ArenaRun rows with
    status IN (champion, refining, needs_review) for this strategy_id — just
    clearing the needs_review flag would leave those 10 exhausted rows in
    place and re-trip the MAX_ROUNDS check on the very next cycle. Delete
    the exhausted round history instead so it starts a clean round 1.
    """
    strategy = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    if not strategy:
        return {"error": f"strategy not found: {strategy_id}"}

    deleted = db.query(ArenaRun).filter_by(strategy_id=strategy_id).delete()
    strategy.arena_status = None
    strategy.arena_rounds = 0
    db.commit()
    return {"strategy_id": strategy_id, "status": "requeued", "cleared_rounds": deleted}

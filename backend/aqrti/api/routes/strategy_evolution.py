"""Strategy Evolution API — /api/v1/strategy-evolution"""

from __future__ import annotations

import sys, os, json

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import StrategyEvolutionHistory
from strategies.strategy_memory import (
    family_survival_memory,
    feature_category_memory,
    regime_family_affinity,
    evolution_tree_summary,
)
from strategies.strategy_registry import count_by_generation
from strategies.meta_learner import run_meta_learning, compute_meta_state

router = APIRouter()


def _safe_json(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return s


@router.get("")
def get_evolution_history(
    days:        int        = Query(default=90, ge=7, le=365),
    operation:   str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(StrategyEvolutionHistory).filter(StrategyEvolutionHistory.evolved_date >= cutoff)
    if operation:
        q = q.filter(StrategyEvolutionHistory.operation.contains(operation))
    if strategy_id:
        q = q.filter(StrategyEvolutionHistory.child_strategy_id == strategy_id)

    rows = q.order_by(StrategyEvolutionHistory.evolved_date.desc()).limit(200).all()
    return {
        "history": [
            {
                "id":                r.id,
                "child_strategy_id": r.child_strategy_id,
                "parent_ids":        _safe_json(r.parent_strategy_ids),
                "evolved_date":      str(r.evolved_date),
                "operation":         r.operation,
                "operation_detail":  _safe_json(r.operation_detail),
                "parent_fitness":    r.parent_fitness,
                "child_fitness":     r.child_fitness,
                "fitness_delta":     r.fitness_delta,
                "regime_at":         r.regime_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/tree")
def get_evolution_tree(
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    return evolution_tree_summary(db, days=days)


@router.get("/generations")
def get_generations(db: Session = Depends(get_db_dependency)):
    return {"by_generation": count_by_generation(db)}


@router.get("/family-survival")
def get_family_survival(db: Session = Depends(get_db_dependency)):
    return family_survival_memory(db)


@router.get("/regime-affinity")
def get_regime_affinity(db: Session = Depends(get_db_dependency)):
    return regime_family_affinity(db)


@router.get("/feature-memory")
def get_feature_memory(db: Session = Depends(get_db_dependency)):
    return feature_category_memory(db)


@router.get("/meta-state")
def get_meta_state(db: Session = Depends(get_db_dependency)):
    """Return the current meta-learning state (family weights, bad features, etc.)."""
    try:
        state = compute_meta_state(db)
        return {"available": True, "meta_state": state}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.post("/meta-learn")
def trigger_meta_learning(db: Session = Depends(get_db_dependency)):
    """
    Manually trigger a full meta-learning cycle.
    Reads all signal sources, adjusts weights, persists insights.
    """
    try:
        result = run_meta_learning(db)
        return {
            "status":          "ok",
            "insights_written": result.get("insights_written", 0),
            "family_weights":  result.get("family_weights", {}),
            "bad_features":    result.get("bad_features", []),
            "conf_floor":      result.get("current_conf_floor"),
            "top_mutation_op": (result.get("ranked_mutation_ops") or [None])[0],
            "regime":          result.get("current_regime"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

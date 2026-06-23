"""
Strategy Memory
Permanent institutional knowledge about strategy behaviour.

Captures:
  - Which feature categories produce the highest-fitness strategies
  - Which families survive the longest
  - Which regimes are most friendly to which families
  - What parameter ranges work best (sharpe-weighted avg thresholds)
  - Evolution trees: parent → child fitness trajectories

This memory informs the generator and evolution engine but does NOT
automatically modify their behaviour — it produces recommendations only.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    StrategyV2, StrategyGraveyard, StrategyEvolutionHistory,
    StrategyResearchReport, KnowledgeEvent,
)
from aqrti.utils.logger import get_logger

log = get_logger("strategy_memory")


def family_survival_memory(db: Session) -> dict:
    """
    For each family: alive count, graveyard count, avg lifetime,
    avg final fitness of dead strategies.
    """
    alive = db.query(StrategyV2).filter(
        StrategyV2.status.in_(["candidate", "shadow", "promoted", "active"])
    ).all()
    dead  = db.query(StrategyGraveyard).all()

    data: dict[str, dict] = {}
    for r in alive:
        f = r.family or "hybrid"
        if f not in data:
            data[f] = {"alive": 0, "dead": 0, "dead_fitness": [], "dead_lifespan": []}
        data[f]["alive"] += 1

    for r in dead:
        f = r.family or "hybrid"
        if f not in data:
            data[f] = {"alive": 0, "dead": 0, "dead_fitness": [], "dead_lifespan": []}
        data[f]["dead"] += 1
        if r.final_fitness is not None:
            data[f]["dead_fitness"].append(r.final_fitness)
        if r.lifespan_days is not None:
            data[f]["dead_lifespan"].append(r.lifespan_days)

    result = {}
    for f, d in data.items():
        total     = d["alive"] + d["dead"]
        surv_rate = d["alive"] / total * 100 if total else 0.0
        result[f] = {
            "family":            f,
            "alive":             d["alive"],
            "dead":              d["dead"],
            "total":             total,
            "survival_rate":     round(surv_rate, 1),
            "avg_dead_fitness":  round(sum(d["dead_fitness"]) / len(d["dead_fitness"]), 1)
                                 if d["dead_fitness"] else None,
            "avg_lifespan_days": round(sum(d["dead_lifespan"]) / len(d["dead_lifespan"]), 1)
                                 if d["dead_lifespan"] else None,
        }
    return result


def feature_category_memory(db: Session) -> dict:
    """
    Which feature categories appear most in high-fitness strategies?
    Builds a weighted frequency map.
    """
    rows = db.query(StrategyV2).filter(StrategyV2.fitness_score.isnot(None)).all()
    cat_fitness: dict[str, list[float]] = {}

    for r in rows:
        if not r.feature_categories:
            continue
        try:
            cats = json.loads(r.feature_categories)
        except Exception:
            continue
        for cat in cats:
            cat_fitness.setdefault(cat, []).append(r.fitness_score)

    result = {}
    for cat, scores in cat_fitness.items():
        result[cat] = {
            "category":      cat,
            "strategy_count": len(scores),
            "avg_fitness":   round(sum(scores) / len(scores), 2),
            "max_fitness":   round(max(scores), 2),
            "top_quartile":  round(sorted(scores, reverse=True)[max(0, len(scores)//4 - 1)], 2),
        }

    # Rank by avg_fitness
    ranked = sorted(result.values(), key=lambda x: x["avg_fitness"], reverse=True)
    return {"by_category": {r["category"]: r for r in ranked}, "ranked": ranked}


def regime_family_affinity(db: Session) -> dict:
    """
    Which families work best in which regimes?
    Based on bull_sharpe / bear_sharpe / sideways_sharpe / volatile_sharpe.
    """
    rows = db.query(StrategyV2).filter(
        StrategyV2.fitness_score.isnot(None),
        StrategyV2.trade_count >= 5,
    ).all()

    affinity: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        f = r.family or "hybrid"
        if f not in affinity:
            affinity[f] = {"BULL": [], "BEAR": [], "SIDEWAYS": [], "VOLATILE": []}
        if r.bull_sharpe:     affinity[f]["BULL"].append(r.bull_sharpe)
        if r.bear_sharpe:     affinity[f]["BEAR"].append(r.bear_sharpe)
        if r.sideways_sharpe: affinity[f]["SIDEWAYS"].append(r.sideways_sharpe)
        if r.volatile_sharpe: affinity[f]["VOLATILE"].append(r.volatile_sharpe)

    result = {}
    for f, regime_data in affinity.items():
        regime_avgs = {}
        best_regime = None
        best_sharpe = -999
        for reg, vals in regime_data.items():
            if vals:
                avg = sum(vals) / len(vals)
                regime_avgs[reg] = round(avg, 4)
                if avg > best_sharpe:
                    best_sharpe = avg
                    best_regime = reg
        result[f] = {
            "family":       f,
            "regime_sharpe": regime_avgs,
            "best_regime":  best_regime,
            "best_sharpe":  round(best_sharpe, 4) if best_sharpe > -999 else None,
        }
    return result


def evolution_tree_summary(db: Session, days: int = 90) -> dict:
    """
    Summarise evolution outcomes: fitness improvement rates, successful operations.
    """
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(StrategyEvolutionHistory)
        .filter(StrategyEvolutionHistory.evolved_date >= cutoff)
        .all()
    )
    by_op: dict[str, dict] = {}
    for r in rows:
        op = (r.operation or "unknown").split(":")[0]
        if op not in by_op:
            by_op[op] = {"count": 0, "positive_delta": 0, "fitness_deltas": []}
        by_op[op]["count"] += 1
        if r.fitness_delta is not None:
            by_op[op]["fitness_deltas"].append(r.fitness_delta)
            if r.fitness_delta > 0:
                by_op[op]["positive_delta"] += 1

    result = {}
    for op, d in by_op.items():
        n = d["count"]
        result[op] = {
            "operation":       op,
            "total":           n,
            "positive_pct":    round(d["positive_delta"] / n * 100, 1) if n else 0,
            "avg_fitness_delta": round(
                sum(d["fitness_deltas"]) / len(d["fitness_deltas"]), 3
            ) if d["fitness_deltas"] else 0,
        }
    return {"days": days, "by_operation": result, "total_events": len(rows)}


def record_knowledge_snapshot(db: Session) -> dict:
    """
    Write a KnowledgeEvent summarising the current strategy population.
    Called daily by the research loop.
    """
    from strategies.strategy_registry import get_population_stats
    stats = get_population_stats(db)

    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "strategy",
        event_type  = "population_snapshot",
        description = (
            f"Strategy population: total={stats['total']} active={stats['active_count']} "
            f"avg_fitness={stats['avg_fitness']} max_fitness={stats['max_fitness']}"
        ),
        outcome     = "neutral",
        magnitude   = stats["avg_fitness"],
        metadata_json = json.dumps(stats),
    )
    db.add(event)
    db.commit()
    log.info("Population snapshot recorded: total=%d active=%d", stats["total"], stats["active_count"])
    return stats

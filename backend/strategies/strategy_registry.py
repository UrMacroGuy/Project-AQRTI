"""
Strategy Registry
Maps strategy_ids to DSL objects, families, and metadata.
Provides fast lookup and family-level aggregation.
"""

from __future__ import annotations

import sys, os, json
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, StrategyGraveyard
from aqrti.utils.logger import get_logger

log = get_logger("strategy_registry")

FAMILIES = [
    "momentum",
    "mean_reversion",
    "breakout",
    "sentiment_driven",
    "regime_adaptive",
    "volume_surge",
    "volatility_play",
    "hybrid",
]

STATUSES = ["candidate", "shadow", "promoted", "active", "retired", "archived"]


def get_family_summary(db: Session) -> dict:
    """Per-family statistics across all live strategies."""
    rows = db.query(StrategyV2).all()
    summary: dict[str, dict] = {}
    for r in rows:
        f = r.family or "hybrid"
        if f not in summary:
            summary[f] = {
                "family":          f,
                "count":           0,
                "active_count":    0,
                "avg_fitness":     [],
                "avg_sharpe":      [],
                "best_strategy_id": None,
                "best_fitness":    None,
            }
        s = summary[f]
        s["count"] += 1
        if r.status in ("active", "promoted"):
            s["active_count"] += 1
        if r.fitness_score is not None:
            s["avg_fitness"].append(r.fitness_score)
            if s["best_fitness"] is None or r.fitness_score > s["best_fitness"]:
                s["best_fitness"]    = r.fitness_score
                s["best_strategy_id"] = r.strategy_id
        if r.sharpe is not None:
            s["avg_sharpe"].append(r.sharpe)

    for s in summary.values():
        s["avg_fitness"] = round(sum(s["avg_fitness"]) / len(s["avg_fitness"]), 2) if s["avg_fitness"] else None
        s["avg_sharpe"]  = round(sum(s["avg_sharpe"])  / len(s["avg_sharpe"]), 4)  if s["avg_sharpe"] else None

    return summary


def get_leaderboard(db: Session, top_n: int = 20, status: str | None = None) -> list[dict]:
    """Top-N strategies ranked by live trade stats from strategy_backtest_trades, falling back to fitness_score."""
    from aqrti.database.models import StrategyBacktestTrade
    from sqlalchemy import func, case

    # Pull real trade stats in one query
    trade_stats = (
        db.query(
            StrategyBacktestTrade.strategy_id,
            func.count(StrategyBacktestTrade.id).label("tc"),
            func.avg(StrategyBacktestTrade.pnl_pct).label("avg_pnl"),
            func.sum(case((StrategyBacktestTrade.pnl_pct > 0, 1), else_=0)).label("wins"),
        )
        .group_by(StrategyBacktestTrade.strategy_id)
        .all()
    )
    live_map: dict[str, dict] = {}
    for row in trade_stats:
        tc = row.tc or 0
        wins = row.wins or 0
        live_map[row.strategy_id] = {
            "real_trade_count": tc,
            "avg_pnl": round(row.avg_pnl or 0, 4),
            "live_win_rate": round(wins * 100.0 / tc, 1) if tc > 0 else 0.0,
        }

    # Build a set of strategy_ids that have real trade data — only fetch those + extras
    # Sorted by trade count desc so the high-trade-count strategies always appear
    live_by_tc = sorted(live_map.items(), key=lambda x: x[1]["real_trade_count"], reverse=True)
    priority_ids = [sid for sid, _ in live_by_tc[:top_n * 3]]

    q = db.query(StrategyV2).filter(StrategyV2.fitness_score.isnot(None))
    if status:
        q = q.filter(StrategyV2.status == status)

    # First: pull strategies with most real trades (guaranteed to have them)
    # Then fall back to top by fitness for any remaining slots
    if priority_ids:
        priority_rows = (
            db.query(StrategyV2)
            .filter(StrategyV2.strategy_id.in_(priority_ids))
            .all()
        )
        seen = {r.strategy_id for r in priority_rows}
        extra_rows = (
            q.filter(~StrategyV2.strategy_id.in_(seen))
            .order_by(StrategyV2.fitness_score.desc())
            .limit(top_n)
            .all()
        )
        rows = priority_rows + extra_rows
    else:
        rows = q.order_by(StrategyV2.fitness_score.desc()).limit(top_n * 3).all()

    # Enrich each row with live stats
    enriched = []
    for r in rows:
        live = live_map.get(r.strategy_id, {})
        real_tc = live.get("real_trade_count", r.trade_count or 0)
        live_wr = live.get("live_win_rate", r.win_rate or 0)
        avg_pnl = live.get("avg_pnl", 0)
        # Score: prefer strategies with actual trades and positive avg P&L
        sort_key = (real_tc > 0, real_tc, avg_pnl)
        enriched.append((sort_key, r, real_tc, live_wr, avg_pnl))

    # Sort: strategies with real trades first, then by trade count desc, then avg_pnl
    enriched.sort(key=lambda x: x[0], reverse=True)

    result = []
    for i, (_, r, real_tc, live_wr, avg_pnl) in enumerate(enriched[:top_n]):
        result.append({
            "rank":          i + 1,
            "strategy_id":   r.strategy_id,
            "name":          r.name or r.strategy_id,
            "family":        r.family,
            "status":        r.status,
            "fitness_score": r.fitness_score,
            "sharpe":        r.sharpe,
            "win_rate":      live_wr if real_tc > 0 else (r.win_rate or 0),
            "avg_pnl_pct":   avg_pnl,
            "profit_factor": r.profit_factor,
            "max_drawdown":  r.max_drawdown,
            "generation":    r.generation,
            "trade_count":   real_tc,
        })
    return result


def resolve_dsl(db: Session, strategy_id: str) -> Optional[dict]:
    """Return the DSL JSON dict for a strategy, or None if not found."""
    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
    if not row or not row.dsl_json:
        return None
    try:
        return json.loads(row.dsl_json)
    except (json.JSONDecodeError, TypeError):
        return None


def count_by_generation(db: Session) -> dict:
    rows = db.query(StrategyV2.generation).all()
    counts: dict[int, int] = {}
    for (g,) in rows:
        counts[g or 0] = counts.get(g or 0, 0) + 1
    return dict(sorted(counts.items()))


def get_graveyard_summary(db: Session) -> dict:
    rows = db.query(StrategyGraveyard).all()
    by_reason: dict[str, int] = {}
    by_family: dict[str, int] = {}
    fitness_vals = []
    for r in rows:
        fr = r.failure_reason or "unknown"
        by_reason[fr] = by_reason.get(fr, 0) + 1
        fam = r.family or "unknown"
        by_family[fam] = by_family.get(fam, 0) + 1
        if r.final_fitness is not None:
            fitness_vals.append(r.final_fitness)
    return {
        "total_buried":   len(rows),
        "by_reason":      by_reason,
        "by_family":      by_family,
        "avg_final_fitness": round(sum(fitness_vals) / len(fitness_vals), 2) if fitness_vals else None,
    }


def get_population_stats(db: Session) -> dict:
    """Aggregate fitness and count stats across the live strategy population."""
    from aqrti.database.models import StrategyGraveyard
    rows = db.query(StrategyV2).all()
    fitness_vals = [r.fitness_score for r in rows if r.fitness_score is not None]
    by_status: dict[str, int] = {}
    max_gen = 0
    for r in rows:
        s = r.status or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
        if (r.generation or 0) > max_gen:
            max_gen = r.generation or 0
    graveyard_count = db.query(StrategyGraveyard).count()
    promoted_count = by_status.get("promoted", 0)
    active_count = by_status.get("active", 0)
    return {
        "total":           len(rows),
        "active_count":    active_count + promoted_count,
        "promoted":        promoted_count,
        "active":          active_count,
        "by_status":       by_status,
        "avg_fitness":     round(sum(fitness_vals) / len(fitness_vals), 2) if fitness_vals else 0.0,
        "max_fitness":     round(max(fitness_vals), 2) if fitness_vals else 0.0,
        "min_fitness":     round(min(fitness_vals), 2) if fitness_vals else 0.0,
        "max_generation":  max_gen,
        "graveyard_count": graveyard_count,
    }

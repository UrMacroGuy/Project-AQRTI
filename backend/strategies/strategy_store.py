"""
Strategy Store
Low-level CRUD operations for StrategyV2 and related tables.
All writes go through here so the rest of the system stays consistent.
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date, datetime
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import (
    StrategyV2, StrategyVersion, StrategyPerformance,
    StrategyEvolutionHistory,
)
from aqrti.utils.logger import get_logger

log = get_logger("strategy_store")


# ── Create / Upsert ──────────────────────────────────────────

def upsert_strategy(db: Session, data: dict) -> StrategyV2:
    """
    Create or update a StrategyV2 row.
    data must contain 'strategy_id'. For inserts, 'family' and 'dsl_json' are required.
    If the row doesn't exist and required fields are missing, the insert is skipped.
    """
    sid = data["strategy_id"]
    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == sid).first()
    if row is None:
        # Only insert if we have the minimum required fields
        if not data.get("family") or not data.get("dsl_json"):
            log.warning("upsert_strategy: skipping insert for %s — missing family/dsl_json", sid)
            return None
        row = StrategyV2(strategy_id=sid)
        db.add(row)

    for k, v in data.items():
        if hasattr(row, k):
            setattr(row, k, v)

    row.updated_at = datetime.utcnow()
    log.debug("Upserted strategy %s  status=%s", sid, row.status)
    return row


def save_version(
    db:           Session,
    strategy_id:  str,
    dsl_json:     str,
    version:      int,
    change_type:  str = "seed",
    change_desc:  str = "",
    fitness_score: Optional[float] = None,
) -> StrategyVersion:
    existing = (
        db.query(StrategyVersion)
        .filter(StrategyVersion.strategy_id == strategy_id,
                StrategyVersion.version     == version)
        .first()
    )
    if existing:
        return existing
    row = StrategyVersion(
        strategy_id   = strategy_id,
        version       = version,
        dsl_json      = dsl_json,
        fitness_score = fitness_score,
        change_type   = change_type,
        change_desc   = change_desc,
    )
    db.add(row)
    return row


def record_evolution_event(
    db:                  Session,
    child_strategy_id:   str,
    operation:           str,
    operation_detail:    dict,
    parent_strategy_ids: list[str] | None = None,
    parent_fitness:      float | None = None,
    child_fitness:       float | None = None,
    regime_at:           str | None = None,
) -> StrategyEvolutionHistory:
    row = StrategyEvolutionHistory(
        child_strategy_id   = child_strategy_id,
        parent_strategy_ids = json.dumps(parent_strategy_ids or []),
        evolved_date        = date.today(),
        operation           = operation,
        operation_detail    = json.dumps(operation_detail),
        parent_fitness      = parent_fitness,
        child_fitness       = child_fitness,
        fitness_delta       = (
            round(child_fitness - parent_fitness, 4)
            if (child_fitness is not None and parent_fitness is not None)
            else None
        ),
        regime_at           = regime_at,
    )
    db.add(row)
    return row


def record_daily_performance(
    db:             Session,
    strategy_id:    str,
    signals_fired:  int = 0,
    trades_opened:  int = 0,
    trades_closed:  int = 0,
    daily_pnl:      float = 0.0,
    daily_pnl_pct:  float = 0.0,
    cumulative_pnl: float = 0.0,
    win_count:      int = 0,
    loss_count:     int = 0,
    regime_at:      str | None = None,
    perf_date:      date | None = None,
) -> StrategyPerformance:
    today = perf_date or date.today()
    existing = (
        db.query(StrategyPerformance)
        .filter(StrategyPerformance.strategy_id == strategy_id,
                StrategyPerformance.date        == today)
        .first()
    )
    if existing:
        return existing
    row = StrategyPerformance(
        strategy_id    = strategy_id,
        date           = today,
        signals_fired  = signals_fired,
        trades_opened  = trades_opened,
        trades_closed  = trades_closed,
        daily_pnl      = daily_pnl,
        daily_pnl_pct  = daily_pnl_pct,
        cumulative_pnl = cumulative_pnl,
        win_count      = win_count,
        loss_count     = loss_count,
        regime_at      = regime_at,
    )
    db.add(row)
    return row


# ── Read ──────────────────────────────────────────────────────

def get_strategy(db: Session, strategy_id: str) -> Optional[StrategyV2]:
    return db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()


def list_strategies(
    db:     Session,
    status: str | None = None,
    family: str | None = None,
    limit:  int = 200,
    order_by: str = "fitness",
) -> list[StrategyV2]:
    q = db.query(StrategyV2)
    if status:
        q = q.filter(StrategyV2.status == status)
    if family:
        q = q.filter(StrategyV2.family == family)
    if order_by == "fitness":
        q = q.order_by(StrategyV2.fitness_score.desc().nullslast())
    elif order_by == "sharpe":
        q = q.order_by(StrategyV2.sharpe.desc().nullslast())
    elif order_by == "recent":
        q = q.order_by(StrategyV2.created_at.desc())
    return q.limit(limit).all()


def get_population_stats(db: Session) -> dict:
    from aqrti.database.models import StrategyGraveyard
    rows = db.query(StrategyV2).all()
    by_status: dict[str, int] = {}
    by_family: dict[str, int] = {}
    fitness_vals = []
    max_gen = 0
    for r in rows:
        by_status[r.status or "unknown"] = by_status.get(r.status or "unknown", 0) + 1
        by_family[r.family or "unknown"] = by_family.get(r.family or "unknown", 0) + 1
        if r.fitness_score is not None:
            fitness_vals.append(r.fitness_score)
        if (r.generation or 0) > max_gen:
            max_gen = r.generation or 0
    graveyard_count = db.query(StrategyGraveyard).count()
    promoted_count = by_status.get("promoted", 0)
    active_count = by_status.get("active", 0)
    return {
        "total":           len(rows),
        "by_status":       by_status,
        "by_family":       by_family,
        "avg_fitness":     round(sum(fitness_vals) / len(fitness_vals), 2) if fitness_vals else 0.0,
        "max_fitness":     round(max(fitness_vals), 2) if fitness_vals else 0.0,
        "active_count":    active_count + promoted_count,
        "promoted":        promoted_count,
        "active":          active_count,
        "max_generation":  max_gen,
        "graveyard_count": graveyard_count,
    }

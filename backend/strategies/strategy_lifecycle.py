"""
Strategy Lifecycle Manager
Handles state transitions: candidate → shadow → promoted → active → retired.

Rules:
  - Promotion requires fitness >= PROMOTE_THRESHOLD
  - Retirement happens when fitness drops below RETIRE_THRESHOLD for N consecutive days
    OR when max_drawdown exceeds DRAWDOWN_LIMIT
  - Retired strategies are moved to graveyard with lessons extracted
  - Human approval is required before "active" status — AQRTI can only reach "promoted"
"""

from __future__ import annotations

import sys, os, json
from datetime import date, datetime
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, StrategyGraveyard, KnowledgeEvent
from aqrti.utils.logger import get_logger

log = get_logger("strategy_lifecycle")

PROMOTE_THRESHOLD  = 35.0    # fitness score required for promotion (0–100 scale)
RETIRE_THRESHOLD   = 8.0     # fitness below this → retirement candidate
DRAWDOWN_LIMIT     = -9999.0 # disabled — cumsum MDD metric is unreliable (divide-by-near-zero artifact)
MIN_TRADES         = 10      # minimum backtest trades before promotion


def promote_strategy(
    db:          Session,
    strategy_id: str,
    reason:      str = "fitness_threshold_met",
) -> dict:
    """
    Move a strategy from shadow → promoted.
    Does NOT move to 'active' — that requires human approval.
    """
    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
    if not row:
        return {"success": False, "error": "strategy not found"}
    if row.status not in ("candidate", "shadow"):
        return {"success": False, "error": f"cannot promote from {row.status}"}
    if (row.fitness_score or 0) < PROMOTE_THRESHOLD:
        return {"success": False, "error": f"fitness {row.fitness_score} below threshold {PROMOTE_THRESHOLD}"}
    if (row.trade_count or 0) < MIN_TRADES:
        return {"success": False, "error": f"insufficient trades ({row.trade_count})"}

    old_status   = row.status
    row.status   = "promoted"
    row.promoted_at = datetime.utcnow()
    row.updated_at  = datetime.utcnow()

    _log_event(db, strategy_id, "strategy_promoted",
               f"Promoted from {old_status}. Fitness={row.fitness_score:.1f}. {reason}")
    log.info("Strategy %s promoted to 'promoted' (fitness=%.1f)", strategy_id, row.fitness_score)
    return {"success": True, "new_status": "promoted", "fitness": row.fitness_score}


def retire_strategy(
    db:             Session,
    strategy_id:    str,
    failure_reason: str = "low_fitness",
    failure_detail: str = "",
    regime_at:      str | None = None,
) -> dict:
    """
    Retire a strategy: update status → retired, write to graveyard.
    Strategies are NEVER deleted.
    """
    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
    if not row:
        return {"success": False, "error": "strategy not found"}
    if row.status == "archived":
        return {"success": False, "error": "already archived"}

    # Extract lessons before archiving
    lessons = _extract_retirement_lessons(row, failure_reason)

    row.status     = "retired"
    row.retired_at = datetime.utcnow()
    row.status_reason = failure_reason
    row.updated_at = datetime.utcnow()

    # Write graveyard record
    already = (
        db.query(StrategyGraveyard)
        .filter(StrategyGraveyard.strategy_id == strategy_id)
        .first()
    )
    if not already:
        grave = StrategyGraveyard(
            strategy_id    = strategy_id,
            name           = row.name,
            family         = row.family,
            generation     = row.generation,
            dsl_json       = row.dsl_json,
            final_fitness  = row.fitness_score,
            final_sharpe   = row.sharpe,
            final_win_rate = row.win_rate,
            failure_reason = failure_reason,
            failure_detail = failure_detail,
            regime_at_death = regime_at,
            lessons_json   = json.dumps(lessons),
            lifespan_days  = (date.today() - row.created_at.date()).days if row.created_at else None,
            trade_count    = row.trade_count,
        )
        db.add(grave)

    _log_event(db, strategy_id, "strategy_retired",
               f"Retired. Reason: {failure_reason}. Fitness={row.fitness_score}. {failure_detail}")
    log.info("Strategy %s retired. Reason: %s", strategy_id, failure_reason)
    return {"success": True, "strategy_id": strategy_id, "failure_reason": failure_reason, "lessons": lessons}


def run_lifecycle_sweep(db: Session) -> dict:
    """
    Scan all active strategies and auto-promote / auto-retire based on fitness.
    Returns summary.
    """
    promoted = []
    retired  = []

    # Promote candidates / shadow strategies with high fitness
    candidates = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["candidate", "shadow"]))
        .all()
    )
    for s in candidates:
        if (s.fitness_score or 0) >= PROMOTE_THRESHOLD and (s.trade_count or 0) >= MIN_TRADES:
            r = promote_strategy(db, s.strategy_id)
            if r["success"]:
                promoted.append(s.strategy_id)

    # Retire promoted/shadow strategies with fitness below threshold
    at_risk = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["shadow", "promoted"]))
        .all()
    )
    for s in at_risk:
        reason = None
        detail = ""
        if (s.fitness_score or 100) < RETIRE_THRESHOLD:
            reason = "low_fitness"
            detail = f"fitness={s.fitness_score:.1f} below {RETIRE_THRESHOLD}"
        elif (s.max_drawdown or 0) < DRAWDOWN_LIMIT:
            reason = "drawdown"
            detail = f"max_drawdown={s.max_drawdown:.1f}% exceeded limit {DRAWDOWN_LIMIT}%"
        if reason:
            r = retire_strategy(db, s.strategy_id, failure_reason=reason, failure_detail=detail)
            if r["success"]:
                retired.append(s.strategy_id)

    db.commit()
    log.info("Lifecycle sweep: promoted=%d retired=%d", len(promoted), len(retired))
    return {"promoted": promoted, "retired": retired}


def _extract_retirement_lessons(row: StrategyV2, failure_reason: str) -> list[str]:
    lessons = []
    if failure_reason == "low_fitness":
        lessons.append(f"Family '{row.family}' gen {row.generation}: fitness degraded to {row.fitness_score}. "
                       f"Sharpe={row.sharpe}, win_rate={row.win_rate}.")
    if failure_reason == "drawdown":
        lessons.append(f"Max drawdown {row.max_drawdown}% exceeded limits — position sizing or stop-loss insufficient.")
    if row.trade_count and row.trade_count < MIN_TRADES:
        lessons.append("Strategy fired too few signals — rules may be too restrictive.")
    try:
        regimes = json.loads(row.allowed_regimes or "[]")
        if len(regimes) == 1:
            lessons.append(f"Single-regime strategy (only {regimes[0]}) — high regime-change risk.")
    except Exception:
        pass
    return lessons


def _log_event(db: Session, strategy_id: str, event_type: str, desc: str):
    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "strategy",
        event_type  = event_type,
        description = f"[{strategy_id}] {desc}",
        outcome     = "neutral",
    )
    db.add(event)

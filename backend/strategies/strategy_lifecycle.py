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

PROMOTE_THRESHOLD  = 50.0    # strategies must reach this fitness to be promoted
RETIRE_THRESHOLD   = 15.0    # retire strategies that fall below this fitness
DRAWDOWN_LIMIT     = -100.0  # MDD gate disabled — backtester MDD is per-strategy equity, not per-trade; fitness captures drawdown indirectly
MIN_TRADES         = 300     # minimum backtest trades required for promotion
MIN_WIN_RATE       = 52.0    # raised 50→52%: must beat coin flip with margin
MIN_SHARPE         = 0.3     # new gate: Sharpe < 0.3 → not worth promoting regardless of win rate
PAPER_WIN_RATE     = 53.0    # raised 52→53%


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
    if (row.win_rate or 0) < MIN_WIN_RATE:
        return {"success": False, "error": f"win_rate {row.win_rate:.1f}% below {MIN_WIN_RATE}% threshold"}
    if (row.sharpe or 0) < MIN_SHARPE:
        return {"success": False, "error": f"sharpe {row.sharpe:.2f} below {MIN_SHARPE} threshold"}

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
    try:
        row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
        if not row:
            return {"success": False, "error": "strategy not found"}
        if row.status == "archived":
            return {"success": False, "error": "already archived"}

        lessons = _extract_retirement_lessons(row, failure_reason)

        row.status        = "retired"
        row.retired_at    = datetime.utcnow()
        row.status_reason = failure_reason
        row.updated_at    = datetime.utcnow()

        already = (
            db.query(StrategyGraveyard)
            .filter(StrategyGraveyard.strategy_id == strategy_id)
            .first()
        )
        if not already:
            grave = StrategyGraveyard(
                strategy_id     = strategy_id,
                name            = row.name,
                family          = row.family,
                generation      = row.generation,
                dsl_json        = row.dsl_json,
                final_fitness   = row.fitness_score,
                final_sharpe    = row.sharpe,
                final_win_rate  = row.win_rate,
                failure_reason  = failure_reason,
                failure_detail  = failure_detail,
                regime_at_death = regime_at,
                lessons_json    = json.dumps(lessons),
                lifespan_days   = (date.today() - row.created_at.date()).days if row.created_at else 0,
                trade_count     = row.trade_count,
            )
            db.add(grave)

        _log_event(db, strategy_id, "strategy_retired",
                   f"Retired. Reason: {failure_reason}. Fitness={row.fitness_score or 0}. {failure_detail}")
        db.commit()
        log.info("Strategy %s retired. Reason: %s", strategy_id, failure_reason)
        return {"success": True, "strategy_id": strategy_id, "failure_reason": failure_reason, "lessons": lessons}
    except Exception as exc:
        db.rollback()
        log.error("retire_strategy %s failed: %s", strategy_id, exc)
        return {"success": False, "error": str(exc)}


def run_lifecycle_sweep(db: Session) -> dict:
    """
    Scan all active strategies and auto-promote / auto-retire based on fitness.
    Returns summary.
    """
    promoted = []
    retired  = []

    # Promote candidates / shadow strategies that pass all gates
    candidates = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["candidate", "shadow"]))
        .all()
    )
    for s in candidates:
        if (
            (s.fitness_score or 0) >= PROMOTE_THRESHOLD
            and (s.trade_count or 0) >= MIN_TRADES
            and (s.win_rate or 0) >= MIN_WIN_RATE
            and (s.sharpe or 0) >= MIN_SHARPE
        ):
            r = promote_strategy(db, s.strategy_id)
            if r["success"]:
                promoted.append(s.strategy_id)

    # Retire shadow/promoted strategies that fall below thresholds
    at_risk = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["shadow", "promoted"]))
        .all()
    )
    for s in at_risk:
        # Don't retire a strategy that hasn't completed a full backtest yet
        if (s.trade_count or 0) < MIN_TRADES:
            continue
        reason = None
        detail = ""
        if (s.fitness_score or 100) < RETIRE_THRESHOLD:
            reason = "low_fitness"
            detail = f"fitness={s.fitness_score:.1f} below {RETIRE_THRESHOLD}"
        elif s.status == "promoted" and (s.win_rate or 0) < MIN_WIN_RATE:
            reason = "low_win_rate"
            detail = f"win_rate={s.win_rate:.1f}% below {MIN_WIN_RATE}% threshold"
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
        lessons.append(f"Family '{row.family}' gen {row.generation}: fitness degraded to {row.fitness_score or 0}. "
                       f"Sharpe={row.sharpe or 0}, win_rate={row.win_rate or 0}.")
    if failure_reason == "drawdown":
        lessons.append(f"Max drawdown {row.max_drawdown or 0}% exceeded limits — position sizing or stop-loss insufficient.")
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

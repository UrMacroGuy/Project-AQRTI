"""
Graveyard Manager
Manages the permanent record of all retired/failed strategies.

Strategies are NEVER deleted. The graveyard provides:
  - Failure pattern analysis (which families fail most)
  - Regime-of-death analysis (when do strategies die)
  - Lesson extraction (what can be learned from each failure)
  - Resurrection candidates (strategies that failed in old regime may work now)

No strategy is removed from the graveyard. It is institutional memory.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyGraveyard, StrategyV2, MarketRegime, KnowledgeEvent
from aqrti.utils.logger import get_logger

log = get_logger("graveyard_manager")

RESURRECTION_FITNESS_GAIN = 10.0    # strategies may be resurrected if regime changed significantly


def bury_strategy(
    db:             Session,
    strategy_id:    str,
    failure_reason: str  = "low_fitness",
    failure_detail: str  = "",
    regime_at:      str | None = None,
    lessons:        list[str] | None = None,
) -> Optional[StrategyGraveyard]:
    """
    Write a strategy to the graveyard. Idempotent — won't duplicate.
    Calls strategy_lifecycle.retire_strategy which writes the grave row.
    """
    existing = db.query(StrategyGraveyard).filter(StrategyGraveyard.strategy_id == strategy_id).first()
    if existing:
        log.debug("Strategy %s already in graveyard", strategy_id)
        return existing

    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
    if not row:
        log.warning("Cannot bury unknown strategy %s", strategy_id)
        return None

    if not regime_at:
        r = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
        regime_at = r[0] if r else "UNKNOWN"

    if lessons is None:
        lessons = _auto_extract_lessons(row, failure_reason)

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

    # Update strategy status
    row.status     = "archived"
    row.status_reason = failure_reason

    _log_event(db, strategy_id, "strategy_buried",
               f"Buried. Reason: {failure_reason}. Regime: {regime_at}. Lessons: {len(lessons)}")
    log.info("Strategy %s buried (reason=%s regime=%s)", strategy_id, failure_reason, regime_at)
    return grave


def get_graveyard(
    db:            Session,
    family:        str | None = None,
    failure_reason: str | None = None,
    limit:         int = 100,
) -> list[dict]:
    q = db.query(StrategyGraveyard)
    if family:
        q = q.filter(StrategyGraveyard.family == family)
    if failure_reason:
        q = q.filter(StrategyGraveyard.failure_reason == failure_reason)
    rows = q.order_by(StrategyGraveyard.buried_at.desc()).limit(limit).all()

    return [
        {
            "strategy_id":    r.strategy_id,
            "name":           r.name,
            "family":         r.family,
            "generation":     r.generation,
            "final_fitness":  r.final_fitness,
            "final_sharpe":   r.final_sharpe,
            "final_win_rate": r.final_win_rate,
            "failure_reason": r.failure_reason,
            "failure_detail": r.failure_detail,
            "regime_at_death": r.regime_at_death,
            "lessons":        _safe_json(r.lessons_json),
            "lifespan_days":  r.lifespan_days,
            "trade_count":    r.trade_count,
            "buried_at":      r.buried_at.isoformat() if r.buried_at else None,
        }
        for r in rows
    ]


def get_resurrection_candidates(db: Session) -> list[dict]:
    """
    Identify graveyard strategies that might perform in the current regime.
    A strategy is a candidate if:
      - It died in a regime different from the current one
      - Its final_fitness was >= 35 (not catastrophically bad)
    """
    current_regime = "BULL"
    r = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
    if r:
        current_regime = r[0]

    rows = (
        db.query(StrategyGraveyard)
        .filter(
            StrategyGraveyard.regime_at_death != current_regime,
            StrategyGraveyard.final_fitness >= 35,
        )
        .order_by(StrategyGraveyard.final_fitness.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "strategy_id":      r.strategy_id,
            "name":             r.name,
            "family":           r.family,
            "final_fitness":    r.final_fitness,
            "died_in_regime":   r.regime_at_death,
            "current_regime":   current_regime,
            "resurrection_note": (
                f"Died in {r.regime_at_death} regime — worth retesting in {current_regime}"
            ),
        }
        for r in rows
    ]


def failure_pattern_analysis(db: Session) -> dict:
    """Aggregate failure patterns across the graveyard."""
    rows    = db.query(StrategyGraveyard).all()
    by_reason: dict[str, int]  = {}
    by_family: dict[str, int]  = {}
    by_regime: dict[str, int]  = {}
    avg_life:  list[int]       = []

    for r in rows:
        fr = r.failure_reason or "unknown"
        fam = r.family or "unknown"
        reg = r.regime_at_death or "UNKNOWN"
        by_reason[fr]  = by_reason.get(fr, 0) + 1
        by_family[fam] = by_family.get(fam, 0) + 1
        by_regime[reg] = by_regime.get(reg, 0) + 1
        if r.lifespan_days:
            avg_life.append(r.lifespan_days)

    most_common_reason = max(by_reason, key=by_reason.get) if by_reason else None
    fragile_family     = max(by_family, key=by_family.get) if by_family else None
    most_deadly_regime = max(by_regime, key=by_regime.get) if by_regime else None

    return {
        "total":                len(rows),
        "by_failure_reason":    by_reason,
        "by_family":            by_family,
        "by_regime_at_death":   by_regime,
        "most_common_reason":   most_common_reason,
        "fragile_family":       fragile_family,
        "most_deadly_regime":   most_deadly_regime,
        "avg_lifespan_days":    round(sum(avg_life) / len(avg_life), 1) if avg_life else None,
    }


def _auto_extract_lessons(row: StrategyV2, failure_reason: str) -> list[str]:
    lessons = []
    if failure_reason == "low_fitness":
        lessons.append(
            f"{row.family.title()} strategy gen {row.generation}: "
            f"fitness fell to {row.fitness_score:.1f}. "
            f"Sharpe={row.sharpe}, win_rate={row.win_rate}%."
        )
    if failure_reason == "drawdown":
        lessons.append(
            f"Max drawdown {row.max_drawdown:.1f}% breached the limit. "
            "Review position sizing or reduce concentration."
        )
    if row.trade_count and row.trade_count < 10:
        lessons.append("Strategy fired < 10 signals in backtest — entry rules too restrictive.")
    if row.profit_factor and row.profit_factor < 1.0:
        lessons.append("Profit factor < 1.0: losses exceeded gains. Rethink entry logic.")
    return lessons


def _safe_json(s):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []


def _log_event(db: Session, strategy_id: str, event_type: str, desc: str):
    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "strategy",
        event_type  = event_type,
        description = f"[{strategy_id}] {desc}",
        outcome     = "negative",
    )
    db.add(event)

"""
Strategy Memory Training — Phase 8.5J
Learns which strategies survive, decay, or fail — and under what conditions.
Every retired strategy becomes institutional memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("strategy_memory")


@dataclass
class StrategyMemoryRecord:
    strategy_id: str
    name: Optional[str]
    family: str
    status: str
    survival_days: int
    final_fitness: Optional[float]
    peak_fitness: Optional[float]
    decay_detected: bool
    failure_reason: Optional[str]
    best_regimes: List[str]
    worst_regimes: List[str]
    lessons: List[str]
    computed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "family": self.family,
            "status": self.status,
            "survival_days": self.survival_days,
            "final_fitness": self.final_fitness,
            "peak_fitness": self.peak_fitness,
            "decay_detected": self.decay_detected,
            "failure_reason": self.failure_reason,
            "best_regimes": self.best_regimes,
            "worst_regimes": self.worst_regimes,
            "lessons": self.lessons,
            "computed_at": self.computed_at,
        }


def build_strategy_memory_record(strategy_id: str, db: Session) -> Optional[StrategyMemoryRecord]:
    """Build a memory record for a single strategy."""
    strat = db.execute(text("""
        SELECT strategy_id, name, family, status, fitness_score,
               sharpe, win_rate, max_drawdown, created_at, updated_at,
               bull_sharpe, bear_sharpe, sideways_sharpe, volatile_sharpe
        FROM strategies_v2 WHERE strategy_id = :sid
        """),
        {"sid": strategy_id},
    ).fetchone()

    if not strat:
        # Try graveyard
        strat = db.execute(text("""
            SELECT strategy_id, name, family, 'retired' as status,
                   final_fitness as fitness_score, NULL as sharpe,
                   final_win_rate as win_rate, NULL as max_drawdown,
                   NULL as created_at, buried_at as updated_at,
                   NULL as bull_sharpe, NULL as bear_sharpe,
                   NULL as sideways_sharpe, NULL as volatile_sharpe
            FROM strategy_graveyard WHERE strategy_id = :sid
            """),
            {"sid": strategy_id},
        ).fetchone()
        if not strat:
            return None

    # Survival days
    survival_days = 0
    if strat.created_at and strat.updated_at:
        try:
            from datetime import datetime as dt
            c = dt.fromisoformat(str(strat.created_at) if isinstance(strat.created_at, str) else strat.created_at)
            u = dt.fromisoformat(str(strat.updated_at) if isinstance(strat.updated_at, str) else strat.updated_at)
            survival_days = max(0, (u - c).days)
        except Exception:
            pass

    # Peak fitness from version history
    peak_row = db.execute(text("SELECT MAX(fitness_score) as peak FROM strategy_versions WHERE strategy_id = :sid"),
        {"sid": strategy_id},
    ).fetchone()
    peak_fitness = float(peak_row.peak) if peak_row and peak_row.peak else strat.fitness_score

    # Decay: fitness dropped >20% from peak
    decay_detected = (
        strat.fitness_score is not None and
        peak_fitness is not None and
        peak_fitness > 0 and
        (peak_fitness - strat.fitness_score) / peak_fitness > 0.20
    )

    # Best/worst regimes from sharpe scores
    regime_sharpes = {
        "BULL": strat.bull_sharpe,
        "BEAR": strat.bear_sharpe,
        "SIDEWAYS": strat.sideways_sharpe,
        "VOLATILE": strat.volatile_sharpe,
    }
    valid = {r: v for r, v in regime_sharpes.items() if v is not None}
    best_regimes = sorted(valid, key=lambda r: valid[r], reverse=True)[:2] if valid else []
    worst_regimes = sorted(valid, key=lambda r: valid[r])[:2] if valid else []

    # Failure reason from graveyard
    grave_row = db.execute(text("SELECT failure_reason, lessons_json FROM strategy_graveyard WHERE strategy_id = :sid"),
        {"sid": strategy_id},
    ).fetchone()
    failure_reason = grave_row.failure_reason if grave_row else None
    lessons_raw = grave_row.lessons_json if grave_row else "[]"
    try:
        lessons = json.loads(lessons_raw or "[]")
    except Exception:
        lessons = []

    record = StrategyMemoryRecord(
        strategy_id=strategy_id,
        name=strat.name,
        family=strat.family,
        status=strat.status,
        survival_days=survival_days,
        final_fitness=float(strat.fitness_score) if strat.fitness_score else None,
        peak_fitness=float(peak_fitness) if peak_fitness else None,
        decay_detected=bool(decay_detected),
        failure_reason=failure_reason,
        best_regimes=best_regimes,
        worst_regimes=worst_regimes,
        lessons=lessons,
    )

    # Persist
    try:
        db.execute(text("""
            INSERT INTO strategy_memory
                (strategy_id, name, family, status, survival_days, final_fitness,
                 peak_fitness, decay_detected, failure_reason, best_regimes_json,
                 worst_regimes_json, lessons_json, computed_at)
            VALUES
                (:sid, :name, :family, :status, :days, :fit, :peak, :decay,
                 :freason, :best, :worst, :lessons, :now)
            ON CONFLICT(strategy_id) DO UPDATE SET
                status = excluded.status,
                survival_days = excluded.survival_days,
                final_fitness = excluded.final_fitness,
                decay_detected = excluded.decay_detected,
                computed_at = excluded.computed_at
            """),
            {
                "sid": record.strategy_id, "name": record.name, "family": record.family,
                "status": record.status, "days": record.survival_days,
                "fit": record.final_fitness, "peak": record.peak_fitness,
                "decay": int(record.decay_detected), "freason": record.failure_reason,
                "best": json.dumps(record.best_regimes), "worst": json.dumps(record.worst_regimes),
                "lessons": json.dumps(record.lessons), "now": record.computed_at,
            },
        )
    except Exception as exc:
        logger.warning("Could not persist strategy memory %s: %s", strategy_id, exc)

    return record


def analyze_family_survival(db: Session) -> Dict[str, Any]:
    """Analyse which strategy families survive longest."""
    rows = db.execute(text("""
        SELECT family,
               AVG(survival_days) as avg_survival,
               AVG(final_fitness) as avg_fitness,
               COUNT(*) as count,
               SUM(CASE WHEN decay_detected = 1 THEN 1 ELSE 0 END) as decay_count
        FROM strategy_memory
        GROUP BY family ORDER BY avg_fitness DESC
        """)
    ).fetchall()
    return {r.family: {
        "avg_survival_days": round(r.avg_survival or 0, 1),
        "avg_fitness": round(r.avg_fitness or 0, 2),
        "count": r.count,
        "decay_rate": round((r.decay_count or 0) / max(r.count, 1), 2),
    } for r in rows}


def run_strategy_memory_pipeline() -> Dict[str, Any]:
    db = get_session_factory()()
    try:
        # Process all strategies (active + retired)
        active_rows = db.execute(text("SELECT strategy_id FROM strategies_v2")).fetchall()
        grave_rows = db.execute(text("SELECT strategy_id FROM strategy_graveyard")).fetchall()
        all_ids = list({r.strategy_id for r in active_rows + grave_rows})

        records = []
        for sid in all_ids:
            try:
                rec = build_strategy_memory_record(sid, db)
                if rec:
                    records.append(rec)
            except Exception as exc:
                logger.error("Failed strategy memory for %s: %s", sid, exc)

        db.commit()

        family_stats = {}
        try:
            family_stats = analyze_family_survival(db)
        except Exception:
            pass

        surviving = sum(1 for r in records if r.status in ("active", "shadow", "promoted"))
        decayed = sum(1 for r in records if r.decay_detected)

        logger.info("Strategy memory: %d strategies processed, %d surviving, %d decayed",
                    len(records), surviving, decayed)

        return {
            "status": "complete",
            "strategies_processed": len(records),
            "surviving": surviving,
            "decayed": decayed,
            "family_survival": family_stats,
        }
    finally:
        db.close()

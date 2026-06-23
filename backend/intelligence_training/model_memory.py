"""
Model Memory — Phase 8.5I
Tracks which models worked, which failed, when, why, and under what regimes.
Generates Model Reliability Scores to guide future model selection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("model_memory")


@dataclass
class ModelReliabilityScore:
    model_name: str
    task: str
    overall_reliability: float       # 0-100
    regime_scores: Dict[str, float]  # regime → reliability
    recent_accuracy: float
    drift_score: float               # 0=stable, 100=severely drifted
    failure_count_30d: int
    success_count_30d: int
    recommendation: str              # trust|caution|retrain|retire
    computed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "task": self.task,
            "overall_reliability": round(self.overall_reliability, 1),
            "regime_scores": {k: round(v, 1) for k, v in self.regime_scores.items()},
            "recent_accuracy": round(self.recent_accuracy, 4),
            "drift_score": round(self.drift_score, 1),
            "failure_count_30d": self.failure_count_30d,
            "success_count_30d": self.success_count_30d,
            "recommendation": self.recommendation,
            "computed_at": self.computed_at,
        }


def _score_to_recommendation(reliability: float, drift: float) -> str:
    if drift > 60:
        return "retrain"
    if reliability >= 70:
        return "trust"
    if reliability >= 50:
        return "caution"
    if reliability >= 30:
        return "retrain"
    return "retire"


def compute_model_reliability(
    model_name: str,
    task: str,
    days_back: int = 90,
    db: Optional[Session] = None,
) -> ModelReliabilityScore:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)

        # Recent walk-forward metrics
        metric_rows = db.execute(
            text("""
            SELECT metric_name, metric_value, computed_at
            FROM model_metrics
            WHERE model_name = :m AND task = :t AND split = 'test' AND computed_at >= :cutoff
            ORDER BY computed_at DESC
            """),
            {"m": model_name, "t": task, "cutoff": cutoff.isoformat()},
        ).fetchall()

        recent_accuracy = 0.0
        if metric_rows:
            acc_vals = [r.metric_value for r in metric_rows if r.metric_name == "accuracy"]
            if acc_vals:
                recent_accuracy = float(np.mean(acc_vals))
        # Drift score from model_drift_history
        drift_rows = db.execute(
            text("""
            SELECT drift_pct, drift_flag FROM model_drift_history
            WHERE model_name = :m AND task = :t AND measured_date >= :cutoff
            ORDER BY measured_date DESC LIMIT 10
            """),
            {"m": model_name, "t": task, "cutoff": cutoff.isoformat()},
        ).fetchall()

        drift_score = 0.0
        if drift_rows:
            drift_flags = sum(1 for r in drift_rows if r.drift_flag)
            drift_pcts = [abs(r.drift_pct or 0) for r in drift_rows]
            drift_score = min(100, float(np.mean(drift_pcts) + drift_flags * 10))

        # Failure/success counts (from predictions using this model)
        fail_row = db.execute(
            text("""
            SELECT
                SUM(CASE WHEN p.success = 0 THEN 1 ELSE 0 END) as failures,
                SUM(CASE WHEN p.success = 1 THEN 1 ELSE 0 END) as successes
            FROM predictions p
            WHERE p.model_version LIKE :m AND p.date >= :cutoff AND p.success IS NOT NULL
            """),
            {"m": f"%{model_name}%", "cutoff": cutoff.isoformat()},
        ).fetchone()

        failure_count = int(fail_row.failures or 0) if fail_row else 0
        success_count = int(fail_row.successes or 0) if fail_row else 0
        total = failure_count + success_count
        win_rate = success_count / total if total > 0 else 0.5

        # Regime-specific reliability
        regime_rows = db.execute(
            text("""
            SELECT p.regime,
                   AVG(CASE WHEN p.success = 1 THEN 1.0 ELSE 0.0 END) as acc,
                   COUNT(*) as cnt
            FROM predictions p
            WHERE p.model_version LIKE :m AND p.date >= :cutoff AND p.success IS NOT NULL
            GROUP BY p.regime
            """),
            {"m": f"%{model_name}%", "cutoff": cutoff.isoformat()},
        ).fetchall()

        regime_scores = {}
        for r in regime_rows:
            if r.regime and r.cnt >= 5:
                regime_scores[r.regime] = float(r.acc or 0) * 100

        # Overall reliability: blend of accuracy + drift penalty
        base_reliability = win_rate * 100
        drift_penalty = drift_score * 0.3
        overall = max(0, min(100, base_reliability - drift_penalty))

        score = ModelReliabilityScore(
            model_name=model_name,
            task=task,
            overall_reliability=overall,
            regime_scores=regime_scores,
            recent_accuracy=recent_accuracy,
            drift_score=drift_score,
            failure_count_30d=failure_count,
            success_count_30d=success_count,
            recommendation=_score_to_recommendation(overall, drift_score),
        )

        # Persist to model_memory table
        try:
            db.execute(
                text("""
                INSERT INTO model_memory
                    (model_name, task, overall_reliability, regime_scores_json,
                     recent_accuracy, drift_score, failure_count, success_count,
                     recommendation, computed_at)
                VALUES
                    (:m, :t, :rel, :reg, :acc, :drift, :fail, :succ, :rec, :now)
                """),
                {
                    "m": model_name, "t": task, "rel": score.overall_reliability,
                    "reg": json.dumps(regime_scores), "acc": recent_accuracy,
                    "drift": drift_score, "fail": failure_count, "succ": success_count,
                    "rec": score.recommendation, "now": score.computed_at,
                },
            )
            db.commit()
        except Exception as exc:
            logger.warning("Could not persist model memory for %s/%s: %s", model_name, task, exc)

        return score
    finally:
        if own_session:
            db.close()


def compute_all_model_reliability(db: Optional[Session] = None) -> Dict[str, ModelReliabilityScore]:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        model_rows = db.execute(
            text("SELECT DISTINCT model_name, task FROM model_versions WHERE is_active = 1")
        ).fetchall()

        scores = {}
        for r in model_rows:
            key = f"{r.model_name}/{r.task}"
            try:
                score = compute_model_reliability(r.model_name, r.task, db=db)
                scores[key] = score
            except Exception as exc:
                logger.error("Failed reliability computation for %s: %s", key, exc)
        return scores
    finally:
        if own_session:
            db.close()


def get_model_memory_records(db=None) -> List[Dict[str, Any]]:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            text("SELECT * FROM model_memory ORDER BY computed_at DESC LIMIT 100")
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            if "regime_scores_json" in d:
                try:
                    d["regime_scores"] = json.loads(d["regime_scores_json"] or "{}")
                except Exception:
                    d["regime_scores"] = {}
            result.append(d)
        return result
    finally:
        if own_session:
            db.close()


def run_model_memory_pipeline() -> Dict[str, Any]:
    logger.info("Starting model memory pipeline")
    scores = compute_all_model_reliability()
    return {
        "status": "complete",
        "models_evaluated": len(scores),
        "scores": {k: v.to_dict() for k, v in scores.items()},
    }

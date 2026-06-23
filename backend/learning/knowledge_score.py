"""
Knowledge Score
Computes the daily AQRTI Intelligence Score (0-100) from 6 components.

Weights:
  prediction_quality   25%
  portfolio_quality    20%
  risk_quality         20%
  learning_quality     15%
  calibration_quality  10%
  feature_quality      10%

A score of 100 means AQRTI is learning optimally, predicting accurately,
and managing risk well. The score delta vs yesterday indicates trajectory.
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import KnowledgeScore, FailureRecord, LessonLearned, KnowledgeEvent
from aqrti.utils.logger import get_logger
from learning.knowledge_metrics import (
    prediction_quality_score,
    portfolio_quality_score,
    risk_quality_score,
    learning_quality_score,
    calibration_quality_score,
    feature_quality_score,
)

log = get_logger("knowledge_score")

WEIGHTS = {
    "prediction_quality":   0.25,
    "portfolio_quality":    0.20,
    "risk_quality":         0.20,
    "learning_quality":     0.15,
    "calibration_quality":  0.10,
    "feature_quality":      0.10,
}


def compute_intelligence_score(db: Session, days: int = 30) -> dict:
    """
    Compute the AQRTI Intelligence Score for today.

    Returns a dict of all components and the overall weighted score.
    """
    components = {
        "prediction_quality":   prediction_quality_score(db, days),
        "portfolio_quality":    portfolio_quality_score(db, days),
        "risk_quality":         risk_quality_score(db, days),
        "learning_quality":     learning_quality_score(db, days),
        "calibration_quality":  calibration_quality_score(db, days),
        "feature_quality":      feature_quality_score(db, days),
    }

    overall = sum(score * WEIGHTS[key] for key, score in components.items())
    overall = round(overall, 2)

    log.info(
        "Intelligence score: overall=%.1f pred=%.1f port=%.1f risk=%.1f learn=%.1f calib=%.1f feat=%.1f",
        overall,
        components["prediction_quality"],
        components["portfolio_quality"],
        components["risk_quality"],
        components["learning_quality"],
        components["calibration_quality"],
        components["feature_quality"],
    )
    return {"overall": overall, **components, "days": days}


def record_daily_score(db: Session, days: int = 30) -> KnowledgeScore:
    """
    Compute today's intelligence score and write to KnowledgeScore table.
    Skips if today's score already exists.

    Returns the KnowledgeScore row.
    """
    today    = date.today()
    existing = db.query(KnowledgeScore).filter(KnowledgeScore.date == today).first()
    if existing:
        log.info("Knowledge score already recorded for %s", today)
        return existing

    scores = compute_intelligence_score(db, days)

    # Delta vs yesterday
    yesterday = today - timedelta(days=1)
    prev      = db.query(KnowledgeScore).filter(KnowledgeScore.date >= yesterday - timedelta(days=3)).order_by(KnowledgeScore.date.desc()).first()
    delta     = round(scores["overall"] - prev.overall_score, 2) if prev else 0.0

    # Event counts
    cutoff       = today - timedelta(days=days)
    events_count = db.query(KnowledgeEvent).filter(KnowledgeEvent.event_date >= cutoff).count()
    fail_count   = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).count()
    lesson_count = db.query(LessonLearned).filter(LessonLearned.lesson_date >= cutoff).count()

    row = KnowledgeScore(
        date                = today,
        overall_score       = scores["overall"],
        prediction_quality  = scores["prediction_quality"],
        portfolio_quality   = scores["portfolio_quality"],
        risk_quality        = scores["risk_quality"],
        learning_quality    = scores["learning_quality"],
        calibration_quality = scores["calibration_quality"],
        feature_quality     = scores["feature_quality"],
        score_delta         = delta,
        events_processed    = events_count,
        failures_detected   = fail_count,
        lessons_generated   = lesson_count,
    )
    db.add(row)
    db.commit()
    log.info("Daily knowledge score recorded: %.1f (delta %+.1f)", scores["overall"], delta)
    return row


def get_score_history(db: Session, days: int = 90) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(KnowledgeScore)
        .filter(KnowledgeScore.date >= cutoff)
        .order_by(KnowledgeScore.date.asc())
        .all()
    )
    return [
        {
            "date":               str(r.date),
            "overall_score":      r.overall_score,
            "prediction_quality": r.prediction_quality,
            "portfolio_quality":  r.portfolio_quality,
            "risk_quality":       r.risk_quality,
            "learning_quality":   r.learning_quality,
            "calibration_quality": r.calibration_quality,
            "feature_quality":    r.feature_quality,
            "score_delta":        r.score_delta,
            "events_processed":   r.events_processed,
            "failures_detected":  r.failures_detected,
            "lessons_generated":  r.lessons_generated,
        }
        for r in rows
    ]


def get_latest_score(db: Session) -> Optional[dict]:
    row = (
        db.query(KnowledgeScore)
        .order_by(KnowledgeScore.date.desc())
        .first()
    )
    if not row:
        return None
    return {
        "date":               str(row.date),
        "overall_score":      row.overall_score,
        "prediction_quality": row.prediction_quality,
        "portfolio_quality":  row.portfolio_quality,
        "risk_quality":       row.risk_quality,
        "learning_quality":   row.learning_quality,
        "calibration_quality": row.calibration_quality,
        "feature_quality":    row.feature_quality,
        "score_delta":        row.score_delta,
        "events_processed":   row.events_processed,
        "failures_detected":  row.failures_detected,
        "lessons_generated":  row.lessons_generated,
    }

"""Learning Center API — /api/v1/learning"""

from __future__ import annotations

import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
learning_dir = os.path.join(os.path.dirname(backend_dir), "backend")
for d in [backend_dir, learning_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import FailureRecord, LessonLearned, KnowledgeEvent

router = APIRouter()


@router.get("")
def get_learning(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    """Main learning overview: intelligence score + failure summary + events."""
    try:
        from learning.knowledge_score import get_latest_score, get_score_history
        latest  = get_latest_score(db) or {}
        history = get_score_history(db, days=min(days, 90))
    except Exception:
        latest  = {}
        history = []

    cutoff   = date.today() - timedelta(days=days)
    failures = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).all()
    lessons  = db.query(LessonLearned).filter(LessonLearned.lesson_date >= cutoff).all()
    events   = (
        db.query(KnowledgeEvent)
        .filter(KnowledgeEvent.event_date >= cutoff)
        .order_by(KnowledgeEvent.event_date.desc())
        .limit(50)
        .all()
    )

    by_cat: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for f in failures:
        by_cat[f.failure_category or "unknown"] = by_cat.get(f.failure_category or "unknown", 0) + 1
        by_sev[f.severity or "medium"] = by_sev.get(f.severity or "medium", 0) + 1

    recent_failures = [
        {
            "id":              f"F-{f.id:04d}",
            "date":            str(f.failure_date),
            "symbol":          f.symbol,
            "category":        f.failure_category,
            "severity":        f.severity,
            "rootCause":       f.root_cause,
            "lesson":          f.lesson,
            "resolved":        f.resolved,
        }
        for f in sorted(failures, key=lambda x: x.failure_date, reverse=True)[:20]
    ]

    return {
        "intelligenceScore":    latest.get("overall_score", 0.0),
        "scoreDelta":           latest.get("score_delta", 0.0),
        "scoreHistory":         history,
        "components": {
            "predictionQuality":   latest.get("prediction_quality", 0.0),
            "portfolioQuality":    latest.get("portfolio_quality", 0.0),
            "riskQuality":         latest.get("risk_quality", 0.0),
            "learningQuality":     latest.get("learning_quality", 0.0),
            "calibrationQuality":  latest.get("calibration_quality", 0.0),
            "featureQuality":      latest.get("feature_quality", 0.0),
        },
        "totalFailures":        len(failures),
        "resolvedFailures":     sum(1 for f in failures if f.resolved),
        "totalLessons":         len(lessons),
        "appliedLessons":       sum(1 for l in lessons if l.applied),
        "failuresByCategory":   by_cat,
        "failuresBySeverity":   by_sev,
        "recentFailures":       recent_failures,
        "recentEvents":         [
            {
                "date":        str(e.event_date),
                "category":    e.category,
                "type":        e.event_type,
                "description": e.description,
                "outcome":     e.outcome,
            }
            for e in events
        ],
        "days":                 days,
    }


@router.post("/run")
def run_learning_loop(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db_dependency),
):
    """Manually trigger the daily learning loop."""
    from learning.learning_loop import run_daily_learning
    return run_daily_learning(days=days)

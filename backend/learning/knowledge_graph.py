"""
Knowledge Graph
In-memory relational view of AQRTI's institutional memory.

Builds a simple symbol-centric graph connecting:
  predictions → outcomes → failures → lessons → regime → patterns

Used by the dashboard to render knowledge timelines and by the
scoring engine to measure learning quality.

Not a graph DB — just structured dicts computed from the SQL tables.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import (
    Prediction, FailureRecord, LessonLearned, PatternOutcome,
    KnowledgeEvent, MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("knowledge_graph")


def build_symbol_graph(db: Session, symbol: str, days: int = 90) -> dict:
    """
    Build a complete picture of everything AQRTI knows about one symbol
    over the last N days.
    """
    cutoff = date.today() - timedelta(days=days)

    predictions = (
        db.query(Prediction)
        .filter(Prediction.symbol == symbol, Prediction.date >= cutoff)
        .order_by(Prediction.date.desc())
        .limit(30)
        .all()
    )
    failures = (
        db.query(FailureRecord)
        .filter(FailureRecord.symbol == symbol, FailureRecord.failure_date >= cutoff)
        .order_by(FailureRecord.failure_date.desc())
        .limit(20)
        .all()
    )
    lessons = (
        db.query(LessonLearned)
        .filter(LessonLearned.symbol == symbol, LessonLearned.lesson_date >= cutoff)
        .order_by(LessonLearned.lesson_date.desc())
        .limit(10)
        .all()
    )
    patterns = (
        db.query(PatternOutcome)
        .filter(PatternOutcome.symbol == symbol, PatternOutcome.prediction_date >= cutoff)
        .order_by(PatternOutcome.prediction_date.desc())
        .limit(10)
        .all()
    )

    correct    = sum(1 for p in predictions if p.actual_return is not None and
                     ((p.direction == "Bullish" and (p.actual_return or 0) > 0) or
                      (p.direction == "Bearish" and (p.actual_return or 0) < 0)))
    total_eval = sum(1 for p in predictions if p.actual_return is not None)

    return {
        "symbol":         symbol,
        "days":           days,
        "predictionCount": len(predictions),
        "failureCount":   len(failures),
        "lessonCount":    len(lessons),
        "patternCount":   len(patterns),
        "accuracy":       round(correct / total_eval * 100, 1) if total_eval else None,
        "recentPredictions": [_pred_node(p) for p in predictions[:10]],
        "recentFailures":    [_failure_node(f) for f in failures[:5]],
        "recentLessons":     [_lesson_node(l) for l in lessons[:5]],
    }


def build_market_graph(db: Session, days: int = 30) -> dict:
    """
    Aggregate knowledge graph across entire universe.
    """
    cutoff = date.today() - timedelta(days=days)

    total_preds   = db.query(Prediction).filter(Prediction.date >= cutoff).count()
    evaluated     = db.query(Prediction).filter(
        Prediction.date >= cutoff, Prediction.actual_return.isnot(None)
    ).count()
    total_fail    = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).count()
    total_lessons = db.query(LessonLearned).filter(LessonLearned.lesson_date >= cutoff).count()
    total_events  = db.query(KnowledgeEvent).filter(KnowledgeEvent.event_date >= cutoff).count()

    regime = db.query(MarketRegime).order_by(MarketRegime.date.desc()).first()

    return {
        "days":           days,
        "totalPredictions":  total_preds,
        "evaluatedPredictions": evaluated,
        "totalFailures":  total_fail,
        "totalLessons":   total_lessons,
        "totalEvents":    total_events,
        "currentRegime":  regime.regime if regime else "UNKNOWN",
        "regimeConfidence": regime.confidence if regime else None,
    }


def _pred_node(p: Prediction) -> dict:
    return {
        "date":          str(p.date),
        "direction":     p.direction,
        "confidence":    p.confidence,
        "expectedReturn": p.expected_return,
        "actualReturn":  p.actual_return,
        "riskLevel":     p.risk_level,
    }


def _failure_node(f: FailureRecord) -> dict:
    return {
        "date":      str(f.failure_date),
        "category":  f.failure_category,
        "severity":  f.severity,
        "rootCause": f.root_cause,
        "lesson":    f.lesson,
    }


def _lesson_node(l: LessonLearned) -> dict:
    return {
        "date":           str(l.lesson_date),
        "title":          l.title,
        "category":       l.category,
        "severity":       l.severity,
        "recommendation": l.recommendation,
    }

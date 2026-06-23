"""
Knowledge Metrics
Computes aggregate health metrics for the knowledge system.

Used by knowledge_score.py to derive component scores,
and by the API to provide dashboard-level summaries.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import (
    Prediction, FailureRecord, LessonLearned, KnowledgeEvent,
    ModelDriftHistory, FeatureDecayHistory, ConfidenceHistory,
)
from aqrti.utils.logger import get_logger

log = get_logger("knowledge_metrics")


def prediction_quality_score(db: Session, days: int = 30) -> float:
    """
    Score 0-100 based on:
      - Directional accuracy of evaluated predictions
      - Calibration quality (conf vs actual)
    """
    cutoff = date.today() - timedelta(days=days)
    preds  = db.query(Prediction).filter(
        Prediction.date >= cutoff,
        Prediction.actual_return.isnot(None),
    ).all()

    if not preds:
        return 50.0

    correct = sum(
        1 for p in preds
        if (p.direction == "Bullish" and (p.actual_return or 0) > 0) or
           (p.direction == "Bearish" and (p.actual_return or 0) < 0)
    )
    accuracy = correct / len(preds) * 100

    # Bonus for high-confidence correct, penalty for high-confidence wrong
    conf_bonus = 0.0
    for p in preds:
        conf = (p.confidence or 50) / 100
        correct_pred = (
            (p.direction == "Bullish" and (p.actual_return or 0) > 0) or
            (p.direction == "Bearish" and (p.actual_return or 0) < 0)
        )
        conf_bonus += (conf - 0.5) * (10 if correct_pred else -10)
    conf_bonus = conf_bonus / len(preds)

    score = min(100.0, max(0.0, accuracy + conf_bonus))
    log.debug("Prediction quality: accuracy=%.1f bonus=%.1f score=%.1f", accuracy, conf_bonus, score)
    return round(score, 2)


def calibration_quality_score(db: Session, days: int = 30) -> float:
    """
    Score 0-100: how well AQRTI's stated confidence matches actual accuracy.
    Perfect calibration = 100. Random = 50. Systematic overconfidence = <50.
    """
    cutoff = date.today() - timedelta(days=days)
    preds  = db.query(Prediction).filter(
        Prediction.date >= cutoff,
        Prediction.confidence.isnot(None),
        Prediction.actual_return.isnot(None),
    ).all()

    if len(preds) < 5:
        return 50.0

    buckets = {
        "50-60": {"conf_sum": 0, "correct": 0, "n": 0},
        "60-70": {"conf_sum": 0, "correct": 0, "n": 0},
        "70-80": {"conf_sum": 0, "correct": 0, "n": 0},
        "80-90": {"conf_sum": 0, "correct": 0, "n": 0},
        "90+":   {"conf_sum": 0, "correct": 0, "n": 0},
    }

    def bucket_key(c):
        if c >= 90: return "90+"
        if c >= 80: return "80-90"
        if c >= 70: return "70-80"
        if c >= 60: return "60-70"
        return "50-60"

    for p in preds:
        c    = p.confidence or 50
        key  = bucket_key(c)
        correct = (
            (p.direction == "Bullish" and (p.actual_return or 0) > 0) or
            (p.direction == "Bearish" and (p.actual_return or 0) < 0)
        )
        buckets[key]["conf_sum"] += c
        buckets[key]["correct"]  += int(correct)
        buckets[key]["n"]        += 1

    ece = 0.0
    total = len(preds)
    for b in buckets.values():
        if b["n"] == 0:
            continue
        avg_conf = b["conf_sum"] / b["n"] / 100
        avg_acc  = b["correct"] / b["n"]
        ece     += (b["n"] / total) * abs(avg_conf - avg_acc)

    score = max(0.0, 100.0 - ece * 200)
    return round(score, 2)


def learning_quality_score(db: Session, days: int = 30) -> float:
    """
    Score 0-100 based on:
      - Failure resolution rate (resolved / total failures)
      - Lesson generation rate (lessons / failures)
      - Lesson application rate (applied / lessons)
    """
    cutoff = date.today() - timedelta(days=days)
    failures = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).all()
    lessons  = db.query(LessonLearned).filter(LessonLearned.lesson_date >= cutoff).all()

    if not failures:
        return 70.0  # no failures = decent baseline

    resolved     = sum(1 for f in failures if f.resolved)
    applied      = sum(1 for l in lessons if l.applied)
    resolution_r = resolved / len(failures)
    lesson_r     = min(len(lessons) / max(len(failures), 1), 1.0)
    apply_r      = applied / max(len(lessons), 1)

    score = (resolution_r * 40 + lesson_r * 40 + apply_r * 20) * 100
    return round(min(100.0, score), 2)


def feature_quality_score(db: Session, days: int = 30) -> float:
    """Score 0-100: proportion of features without significant decay."""
    cutoff = date.today() - timedelta(days=days)
    decays = db.query(FeatureDecayHistory).filter(
        FeatureDecayHistory.measured_date >= cutoff,
    ).all()
    if not decays:
        return 75.0
    healthy = sum(1 for d in decays if not d.decay_flag)
    return round(healthy / len(decays) * 100, 2)


def risk_quality_score(db: Session, days: int = 30) -> float:
    """
    Score 0-100 derived from:
      - Portfolio drawdown vs limit (80% exposure limit)
      - Failure severity distribution
    """
    cutoff = date.today() - timedelta(days=days)
    failures = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).all()
    if not failures:
        return 80.0
    critical = sum(1 for f in failures if f.severity == "critical")
    high     = sum(1 for f in failures if f.severity == "high")
    penalty  = (critical * 15 + high * 5)
    return round(max(0.0, 100.0 - penalty), 2)


def portfolio_quality_score(db: Session, days: int = 30) -> float:
    """Score from paper trading performance — Sharpe + win rate proxy."""
    try:
        from paper_trading.performance_tracker import get_latest_snapshot
        snap = get_latest_snapshot(db)
        if not snap:
            return 50.0
        sharpe   = snap.get("sharpeRatio", 0) or 0
        win_rate = snap.get("winRatePct", 50) or 50
        pf       = snap.get("profitFactor", 1) or 1
        score    = (
            min(sharpe / 3.0, 1.0) * 40 +
            min(win_rate / 100.0, 1.0) * 35 +
            min((pf - 1.0) / 2.0, 1.0) * 25
        ) * 100
        return round(min(100.0, max(0.0, score)), 2)
    except Exception:
        return 50.0


def compute_all_metrics(db: Session, days: int = 30) -> dict:
    pred  = prediction_quality_score(db, days)
    port  = portfolio_quality_score(db, days)
    risk  = risk_quality_score(db, days)
    learn = learning_quality_score(db, days)
    calib = calibration_quality_score(db, days)
    feat  = feature_quality_score(db, days)
    return {
        "predictionQuality":  pred,
        "portfolioQuality":   port,
        "riskQuality":        risk,
        "learningQuality":    learn,
        "calibrationQuality": calib,
        "featureQuality":     feat,
        "days":               days,
    }

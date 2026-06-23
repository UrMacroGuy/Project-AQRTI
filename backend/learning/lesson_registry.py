"""
Lesson Registry
Creates, stores, and retrieves actionable lessons learned.

Lessons are generated automatically by:
  - root_cause_engine (from failures)
  - pattern_evaluator (from pattern outcomes)
  - confidence_audit (from calibration gaps)
  - model_drift detector (from drift events)

Each lesson answers: what happened, why it happened,
what worked, what failed, and what to do differently.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import LessonLearned, FailureRecord
from aqrti.utils.logger import get_logger

log = get_logger("lesson_registry")

CATEGORIES = ["prediction", "portfolio", "risk", "model", "feature", "pattern", "calibration", "regime"]


def record_lesson(
    db:               Session,
    category:         str,
    title:            str,
    description:      str  = "",
    what_happened:    str  = "",
    why_it_happened:  str  = "",
    what_worked:      str  = "",
    what_failed:      str  = "",
    recommendation:   str  = "",
    severity:         str  = "info",       # info|warning|critical
    symbol:           Optional[str]  = None,
    regime:           Optional[str]  = None,
    source_failure_id: Optional[int] = None,
    lesson_date:      Optional[date] = None,
) -> LessonLearned:
    row = LessonLearned(
        lesson_date      = lesson_date or date.today(),
        category         = category,
        title            = title,
        description      = description,
        what_happened    = what_happened,
        why_it_happened  = why_it_happened,
        what_worked      = what_worked,
        what_failed      = what_failed,
        recommendation   = recommendation,
        severity         = severity,
        symbol           = symbol,
        regime           = regime,
        source_failure_id = source_failure_id,
    )
    db.add(row)
    db.flush()
    log.info("Lesson recorded: [%s] %s", category, title)
    return row


def get_lessons(
    db:       Session,
    days:     int = 90,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit:    int = 100,
) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    q = db.query(LessonLearned).filter(LessonLearned.lesson_date >= cutoff)
    if category:
        q = q.filter(LessonLearned.category == category)
    if severity:
        q = q.filter(LessonLearned.severity == severity)
    rows = q.order_by(LessonLearned.lesson_date.desc()).limit(limit).all()
    return [_lesson_to_dict(r) for r in rows]


def get_lesson_summary(db: Session, days: int = 30) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows   = db.query(LessonLearned).filter(LessonLearned.lesson_date >= cutoff).all()
    by_cat  = {}
    by_sev  = {}
    applied = 0
    for r in rows:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
        by_sev[r.severity] = by_sev.get(r.severity, 0) + 1
        if r.applied:
            applied += 1
    return {
        "total":      len(rows),
        "applied":    applied,
        "byCategory": by_cat,
        "bySeverity": by_sev,
        "days":       days,
    }


def _lesson_to_dict(r: LessonLearned) -> dict:
    return {
        "id":             r.id,
        "date":           str(r.lesson_date),
        "category":       r.category,
        "title":          r.title,
        "description":    r.description,
        "whatHappened":   r.what_happened,
        "whyItHappened":  r.why_it_happened,
        "whatWorked":     r.what_worked,
        "whatFailed":     r.what_failed,
        "recommendation": r.recommendation,
        "severity":       r.severity,
        "symbol":         r.symbol,
        "regime":         r.regime,
        "applied":        r.applied,
    }

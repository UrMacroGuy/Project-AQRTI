"""Lessons API — /api/v1/lessons"""

from __future__ import annotations

import sys, os
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import LessonLearned

router = APIRouter()


@router.get("")
def get_lessons(
    days:     int = Query(default=90, ge=1, le=365),
    category: str = Query(default=None),
    severity: str = Query(default=None),
    symbol:   str = Query(default=None),
    limit:    int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    from learning.lesson_registry import get_lessons, get_lesson_summary
    lessons = get_lessons(db, days=days, category=category, severity=severity, limit=limit)
    summary = get_lesson_summary(db, days=days)
    return {
        "lessons": lessons,
        "summary": summary,
        "days":    days,
    }


@router.get("/summary")
def get_lesson_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from learning.lesson_registry import get_lesson_summary
    return get_lesson_summary(db, days=days)


@router.patch("/{lesson_id}/apply")
def apply_lesson(
    lesson_id: int,
    db: Session = Depends(get_db_dependency),
):
    row = db.query(LessonLearned).filter(LessonLearned.id == lesson_id).first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Lesson not found")
    row.applied = True
    db.commit()
    return {"id": lesson_id, "applied": True}


@router.get("/calibration")
def get_calibration(
    days: int = Query(default=30, ge=7, le=180),
    db: Session = Depends(get_db_dependency),
):
    from learning.confidence_audit import build_calibration_curve
    return build_calibration_curve(db, days=days)

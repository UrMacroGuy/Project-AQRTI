"""Model Drift API — /api/v1/drift"""

from __future__ import annotations

import sys, os
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("")
def get_drift_summary(
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    from learning.model_drift import get_drift_summary
    return get_drift_summary(db, days=days)


@router.get("/performance")
def get_model_performance(
    days: int = Query(default=30, ge=7, le=180),
    db: Session = Depends(get_db_dependency),
):
    from learning.model_performance import analyze_all_models
    return analyze_all_models(db, days=days)


@router.get("/weights")
def get_weight_recommendation(
    task: str = Query(default="direction"),
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db_dependency),
):
    from learning.weight_optimizer import compute_recommended_weights
    return compute_recommended_weights(db, task=task, days=days)


@router.post("/run")
def trigger_drift_detection(
    db: Session = Depends(get_db_dependency),
):
    from learning.model_drift import run_drift_detection
    return run_drift_detection(db, windows=[30, 90])

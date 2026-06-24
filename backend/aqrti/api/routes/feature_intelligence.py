"""Feature Intelligence API — /api/v1/feature-intelligence"""

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
def get_feature_intelligence(
    days: int = Query(default=30, ge=7, le=180),
    db: Session = Depends(get_db_dependency),
):
    from learning.feature_ranker import rank_features, get_ranking_summary
    from learning.feature_decay_detector import get_decay_summary
    from learning.feature_importance_tracker import get_importance_summary

    ranking  = rank_features(db, days=days)
    rsummary = get_ranking_summary(db, days=days)
    decay    = get_decay_summary(db, days=days)
    imp_sum  = get_importance_summary(db, days=days)

    return {
        "ranking":       ranking,
        "summary":       rsummary,
        "decaySummary":  decay,
        "importanceMeta": imp_sum,
        "days":          days,
    }


@router.get("/ranking")
def get_ranking(
    days:       int = Query(default=30, ge=7, le=180),
    model_name: str = Query(default=None),
    task:       str = Query(default=None),
    db: Session = Depends(get_db_dependency),
):
    from learning.feature_ranker import rank_features
    features = rank_features(db, model_name=model_name, task=task, days=days)

    if not features:
        # Fall back: compute feature statistics from feature_values table
        from aqrti.database.models import FeatureValue
        from sqlalchemy import func
        stats = (
            db.query(
                FeatureValue.feature_name,
                func.count(FeatureValue.id).label("n"),
                func.avg(FeatureValue.value).label("avg_val"),
            )
            .group_by(FeatureValue.feature_name)
            .order_by(func.count(FeatureValue.id).desc())
            .limit(30)
            .all()
        )
        features = [
            {
                "featureName": r.feature_name,
                "importanceScore": None,
                "decaySeverity": "none",
                "recommendation": "keep",
                "sampleCount": r.n,
                "avgValue": round(float(r.avg_val), 4) if r.avg_val is not None else None,
                "source": "feature_values",
            }
            for r in stats
        ]

    return {"features": features, "days": days}


@router.get("/decay")
def get_decay(
    days: int = Query(default=30, ge=7, le=180),
    db: Session = Depends(get_db_dependency),
):
    from learning.feature_decay_detector import get_decay_summary
    return get_decay_summary(db, days=days)


@router.get("/importance")
def get_importance(
    days:   int = Query(default=30, ge=7, le=180),
    top_n:  int = Query(default=20, ge=5, le=100),
    db: Session = Depends(get_db_dependency),
):
    from learning.feature_importance_tracker import get_top_features
    return {"features": get_top_features(db, top_n=top_n, days=days), "days": days}


@router.post("/decay/run")
def run_decay(
    db: Session = Depends(get_db_dependency),
):
    from learning.feature_decay_detector import run_decay_detection
    return run_decay_detection(db)

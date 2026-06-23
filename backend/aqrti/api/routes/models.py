"""
Models API — /api/v1/models
Returns model registry, metrics, and walk-forward validation results.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import ModelVersion, ModelMetric, WalkForwardFold

router = APIRouter()


@router.get("")
def get_models(
    task:   str     = Query(default="all"),
    db:     Session = Depends(get_db_dependency),
):
    """List all registered model versions."""
    q = db.query(ModelVersion)
    if task != "all":
        q = q.filter_by(task=task)
    rows = q.order_by(ModelVersion.trained_at.desc()).all()

    return [
        {
            "id":                r.id,
            "modelName":         r.model_name,
            "task":              r.task,
            "labelCol":          r.label_col,
            "version":           r.version,
            "primaryMetric":     r.primary_metric,
            "metrics":           json.loads(r.metrics_json or "{}"),
            "featureImportance": json.loads(r.importance_json or "{}"),
            "trainRows":         r.train_rows,
            "trainedAt":         str(r.trained_at) if r.trained_at else None,
            "isActive":          r.is_active,
        }
        for r in rows
    ]


@router.get("/stats")
def get_model_stats(db: Session = Depends(get_db_dependency)):
    """Summary statistics for the Model Center page."""
    versions = db.query(ModelVersion).filter_by(is_active=True).all()
    if not versions:
        return {"available": False, "activeModels": 0}

    folds_count = db.query(func.count(WalkForwardFold.id)).scalar() or 0

    dir_models = [v for v in versions if v.task == "direction"]
    best_auc   = None
    if dir_models:
        aucs = [json.loads(v.metrics_json or "{}").get("auc_roc") for v in dir_models]
        aucs = [a for a in aucs if a is not None]
        best_auc = round(max(aucs), 4) if aucs else None

    ret_models = [v for v in versions if v.task == "expected_return"]
    best_ic    = None
    if ret_models:
        ics = [json.loads(v.metrics_json or "{}").get("ic") for v in ret_models]
        ics = [ic for ic in ics if ic is not None]
        best_ic = round(max(ics), 4) if ics else None

    trained_ats = [v.trained_at for v in versions if v.trained_at]
    last_trained = str(max(trained_ats)) if trained_ats else None

    return {
        "available":      True,
        "activeModels":   len(versions),
        "totalFolds":     folds_count,
        "bestAUC":        best_auc,
        "bestIC":         best_ic,
        "lastTrainedAt":  last_trained,
        "modelTypes":     list({v.model_name for v in versions}),
        "tasks":          list({v.task for v in versions}),
    }


@router.get("/metrics")
def get_model_metrics(
    model_name: str     = Query(default="all"),
    task:       str     = Query(default="all"),
    split:      str     = Query(default="test"),
    db:         Session = Depends(get_db_dependency),
):
    """Raw metrics from walk-forward validation."""
    q = db.query(ModelMetric).filter_by(split=split)
    if model_name != "all":
        q = q.filter_by(model_name=model_name)
    if task != "all":
        q = q.filter_by(task=task)

    rows = q.order_by(ModelMetric.fold, ModelMetric.model_name).all()

    return [
        {
            "modelName":   r.model_name,
            "task":        r.task,
            "version":     r.version,
            "fold":        r.fold,
            "metricName":  r.metric_name,
            "metricValue": r.metric_value,
            "split":       r.split,
            "computedAt":  str(r.computed_at),
        }
        for r in rows
    ]


@router.get("/walk-forward")
def get_walk_forward_folds(
    task: str     = Query(default="all"),
    db:   Session = Depends(get_db_dependency),
):
    """All walk-forward fold metadata."""
    q = db.query(WalkForwardFold)
    if task != "all":
        q = q.filter_by(task=task)
    rows = q.order_by(WalkForwardFold.fold).all()

    return [
        {
            "modelName":  r.model_name,
            "task":       r.task,
            "version":    r.version,
            "fold":       r.fold,
            "trainStart": r.train_start,
            "trainEnd":   r.train_end,
            "testStart":  r.test_start,
            "testEnd":    r.test_end,
            "trainRows":  r.train_rows,
            "testRows":   r.test_rows,
            "status":     r.status,
        }
        for r in rows
    ]

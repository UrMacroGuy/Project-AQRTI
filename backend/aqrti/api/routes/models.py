"""
Models API — /api/v1/models
Returns model registry, metrics, and walk-forward validation results.
Reads from model_metrics + walk_forward_folds (populated by ML retrainer).
model_versions is a secondary registry; data lives in model_metrics.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

import sys, os
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import ModelVersion, ModelMetric, WalkForwardFold

router = APIRouter()

try:
    from ml.model_retrainer import check_and_retrain, get_retraining_status
    _RETRAINER_AVAILABLE = True
except Exception:
    _RETRAINER_AVAILABLE = False


def _model_names_from_metrics(db: Session) -> list[str]:
    rows = db.query(ModelMetric.model_name).distinct().all()
    return [r[0] for r in rows]


def _best_metric(db: Session, model_name: str, metric_name: str) -> float | None:
    row = db.query(func.max(ModelMetric.metric_value)).filter(
        ModelMetric.model_name == model_name,
        ModelMetric.metric_name == metric_name,
        ModelMetric.split == "test",
    ).scalar()
    return float(row) if row is not None else None


def _latest_fold_date(db: Session) -> str | None:
    row = db.query(func.max(ModelMetric.computed_at)).scalar()
    return str(row) if row else None


@router.get("")
def get_models(
    task:   str     = Query(default="all"),
    db:     Session = Depends(get_db_dependency),
):
    """List all registered model versions. Falls back to model_metrics if model_versions is empty."""
    # Try model_versions first
    q = db.query(ModelVersion)
    if task != "all":
        q = q.filter_by(task=task)
    rows = q.order_by(ModelVersion.trained_at.desc()).all()

    if rows:
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

    # Fallback: synthesise model list from model_metrics
    model_names = _model_names_from_metrics(db)
    result = []
    for name in model_names:
        # get all tasks for this model
        tasks = [r[0] for r in db.query(ModelMetric.task).filter(
            ModelMetric.model_name == name).distinct().all()]
        for t in tasks:
            if task != "all" and t != task:
                continue
            acc  = _best_metric(db, name, "accuracy")
            auc  = _best_metric(db, name, "auc_roc")
            ece  = _best_metric(db, name, "ece")
            last = _latest_fold_date(db)
            result.append({
                "id":                None,
                "modelName":         name,
                "task":              t,
                "labelCol":          "direction_5d" if t == "direction" else t,
                "version":           1,
                "primaryMetric":     auc or acc,
                "metrics":           {"accuracy": acc, "auc_roc": auc, "ece": ece},
                "featureImportance": {},
                "trainRows":         None,
                "trainedAt":         last,
                "isActive":          True,
            })
    return result


@router.get("/stats")
def get_model_stats(db: Session = Depends(get_db_dependency)):
    """Summary statistics for the Model Center page."""
    # Try model_versions first
    versions = db.query(ModelVersion).filter_by(is_active=True).all()

    if versions:
        folds_count = db.query(func.count(WalkForwardFold.id)).scalar() or 0
        dir_models = [v for v in versions if v.task == "direction"]
        best_auc = None
        if dir_models:
            aucs = [json.loads(v.metrics_json or "{}").get("auc_roc") for v in dir_models]
            aucs = [a for a in aucs if a is not None]
            best_auc = round(max(aucs), 4) if aucs else None
        trained_ats = [v.trained_at for v in versions if v.trained_at]
        last_trained = str(max(trained_ats)) if trained_ats else None
        return {
            "available":      True,
            "activeModels":   len(versions),
            "totalFolds":     folds_count,
            "bestAUC":        best_auc,
            "lastTrainedAt":  last_trained,
            "modelTypes":     list({v.model_name for v in versions}),
            "tasks":          list({v.task for v in versions}),
        }

    # Fallback: synthesise from model_metrics
    model_names = _model_names_from_metrics(db)
    if not model_names:
        return {"available": False, "activeModels": 0}

    folds_count = db.query(func.count(WalkForwardFold.id)).scalar() or 0

    best_auc = None
    for name in model_names:
        auc = _best_metric(db, name, "auc_roc")
        if auc and (best_auc is None or auc > best_auc):
            best_auc = auc

    best_acc = None
    for name in model_names:
        acc = _best_metric(db, name, "accuracy")
        if acc and (best_acc is None or acc > best_acc):
            best_acc = acc

    ece_row = db.query(func.avg(ModelMetric.metric_value)).filter(
        ModelMetric.metric_name == "ece", ModelMetric.split == "test").scalar()

    last_trained = _latest_fold_date(db)
    tasks = [r[0] for r in db.query(ModelMetric.task).distinct().all()]

    return {
        "available":      True,
        "activeModels":   len(model_names),
        "totalFolds":     folds_count,
        "bestAUC":        round(best_auc, 4) if best_auc else None,
        "bestAccuracy":   round(best_acc, 4) if best_acc else None,
        "avgECE":         round(float(ece_row), 4) if ece_row else None,
        "lastTrainedAt":  last_trained,
        "modelTypes":     model_names,
        "tasks":          tasks,
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


@router.get("/retrain-status")
def get_retrain_status(db: Session = Depends(get_db_dependency)):
    """Check whether model retraining is needed."""
    if not _RETRAINER_AVAILABLE:
        return {"available": False, "reason": "ml_retrainer_not_importable"}
    try:
        status = get_retraining_status(db)
        return {"available": True, **status}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.post("/retrain")
def trigger_retrain(
    force: bool     = False,
    db:    Session  = Depends(get_db_dependency),
):
    """
    Trigger model retraining.
    - force=false: retrain only if accuracy or staleness thresholds are breached
    - force=true:  retrain regardless
    """
    if not _RETRAINER_AVAILABLE:
        return {"status": "unavailable", "reason": "ml_retrainer_not_importable"}
    try:
        result = check_and_retrain(db, force=force)
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

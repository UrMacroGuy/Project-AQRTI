"""
AQRTI Backtest Validator
Trains final production models on all available data (post walk-forward validation),
saves artifacts, and registers them in the model_versions table.

Also provides run_full_training() which is the main entry point called by the scheduler.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.datasets.training_dataset import (
    TrainingDataset,
    prepare_training_dataset,
    get_final_train_test,
)
from ml.models.lightgbm_model import LightGBMModel
from ml.models.xgboost_model import XGBoostModel
from ml.models.catboost_model import CatBoostModel
from ml.models.base_model import BaseModel, ModelArtifact, ML_MODELS_DIR
from ml.validation.metrics import compute_metrics
from ml.validation.walk_forward import run_walk_forward_validation

log = get_logger("backtest_validator")

MODEL_CLASSES = {
    "lightgbm": LightGBMModel,
    "xgboost":  XGBoostModel,
    "catboost": CatBoostModel,
}

# Tasks to train models for
TRAINING_TASKS = [
    ("direction_5d",    "direction"),
    ("expected_return", "expected_return"),
    ("outperform_binary", "direction"),
]


def train_final_model(
    dataset: TrainingDataset,
    model_name: str,
    version: int = 1,
) -> Optional[BaseModel]:
    """
    Train a single model on the full dataset (80/20 chronological split for final eval).
    Saves the artifact and returns the trained model.
    """
    ModelClass = MODEL_CLASSES[model_name]
    task       = dataset.label_col
    is_classif = task in ("direction_5d", "outperform_binary")
    ml_task    = "direction" if is_classif else "expected_return"

    X_train, y_train, X_test, y_test, scaler = get_final_train_test(dataset, scale=True)

    if len(X_train) < 50:
        log.warning("Insufficient training rows for %s — skipping", model_name)
        return None

    # Use last 15% of train as early-stopping validation
    val_split = int(len(X_train) * 0.85)
    X_tr = X_train.iloc[:val_split]
    y_tr = y_train.iloc[:val_split]
    X_vl = X_train.iloc[val_split:]
    y_vl = y_train.iloc[val_split:]

    model = ModelClass(task=ml_task, label_col=task, version=version)
    try:
        model.fit(X_tr, y_tr, X_vl, y_vl)
    except Exception as exc:
        log.error("Final training failed for %s/%s: %s", model_name, task, exc)
        return None

    # Evaluate on hold-out test set
    y_pred  = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    metrics = compute_metrics(y_test, y_pred, y_proba, ml_task)

    importance = model.feature_importance()

    # Attach artifact metadata
    model._artifact = ModelArtifact(
        model_type        = model_name,
        task              = ml_task,
        label_col         = task,
        version           = version,
        feature_cols      = dataset.feature_cols,
        hyperparams       = model.hyperparams,
        train_rows        = len(X_train),
        trained_at        = datetime.utcnow(),
        final_metrics     = metrics,
        feature_importance = importance,
    )

    path = model.save()

    _register_model_version(model_name, ml_task, task, version, path, metrics, importance, len(X_train))

    log.info(
        "Final model saved: %s/%s v%d | test metrics: %s",
        model_name, task, version,
        {k: round(v, 4) for k, v in metrics.items()},
    )
    return model


def _register_model_version(
    model_name: str,
    task:       str,
    label_col:  str,
    version:    int,
    path:       Path,
    metrics:    dict,
    importance: dict,
    train_rows: int,
) -> None:
    """Register or update a model in the model_versions table."""
    try:
        import json
        from aqrti.database.engine import get_db
        from aqrti.database.models import ModelVersion

        with get_db() as db:
            existing = (
                db.query(ModelVersion)
                .filter_by(model_name=model_name, task=task, version=version)
                .first()
            )
            # Primary metric
            primary = metrics.get("auc_roc") or metrics.get("ic") or 0.0

            if existing:
                existing.artifact_path     = str(path)
                existing.primary_metric    = primary
                existing.metrics_json      = json.dumps(metrics)
                existing.importance_json   = json.dumps(dict(list(importance.items())[:20]))
                existing.train_rows        = train_rows
                existing.trained_at        = datetime.utcnow()
                existing.is_active         = True
            else:
                db.add(ModelVersion(
                    model_name      = model_name,
                    task            = task,
                    label_col       = label_col,
                    version         = version,
                    artifact_path   = str(path),
                    primary_metric  = primary,
                    metrics_json    = json.dumps(metrics),
                    importance_json = json.dumps(dict(list(importance.items())[:20])),
                    train_rows      = train_rows,
                    trained_at      = datetime.utcnow(),
                    is_active       = True,
                ))
            db.commit()
    except Exception as exc:
        log.error("Failed to register model version: %s", exc)


def run_full_training(version: int = 1) -> dict:
    """
    Complete training pipeline:
      1. Walk-forward validation for all tasks
      2. Final model training and registration

    Returns summary dict with results for each task.
    """
    results = {}

    for label_col, ml_task in TRAINING_TASKS:
        log.info("=== Training task: %s (ml_task=%s) ===", label_col, ml_task)
        try:
            dataset = prepare_training_dataset(label_col=label_col, version=version)
            if dataset.df.empty or not dataset.folds:
                log.warning("Skipping %s — no data or folds", label_col)
                results[label_col] = {"status": "skipped", "reason": "no_data"}
                continue

            # Walk-forward validation
            wf_results = run_walk_forward_validation(dataset, version=version)

            # Train final production models
            trained_models = {}
            for model_name in MODEL_CLASSES:
                model = train_final_model(dataset, model_name, version)
                trained_models[model_name] = "ok" if model else "failed"

            results[label_col] = {
                "status":        "ok",
                "folds":         wf_results.get("total_folds", 0),
                "best_model":    wf_results.get("best_model"),
                "models_trained": trained_models,
                "aggregated":    wf_results.get("aggregated", {}),
            }
        except Exception as exc:
            log.error("Training pipeline failed for %s: %s", label_col, exc)
            results[label_col] = {"status": "error", "error": str(exc)}

    log.info("=== Full training complete ===")
    return results


def load_active_models() -> dict[str, dict[str, BaseModel]]:
    """
    Load all active trained models from disk.

    Returns:
        {label_col: {model_name: BaseModel instance}}
    """
    active: dict[str, dict[str, BaseModel]] = {}

    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import ModelVersion

        with get_db() as db:
            rows = db.query(ModelVersion).filter_by(is_active=True).all()
            # Eagerly extract all attributes before session closes
            row_data = [
                (row.model_name, row.label_col, row.version, row.artifact_path)
                for row in rows
            ]

        for model_name, label_col, version, artifact_path in row_data:
            path = Path(artifact_path)
            if not path.exists():
                log.warning("Model artifact missing: %s", path)
                continue

            ModelClass = MODEL_CLASSES.get(model_name)
            if not ModelClass:
                continue

            try:
                model = ModelClass.load(path)
                if label_col not in active:
                    active[label_col] = {}
                active[label_col][model_name] = model
                log.info("Loaded %s/%s v%d from %s", model_name, label_col, version, path)
            except Exception as exc:
                log.error("Failed to load %s: %s", path, exc)

    except Exception as exc:
        log.error("load_active_models failed: %s", exc)

    return active

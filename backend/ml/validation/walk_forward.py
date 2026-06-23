"""
AQRTI Walk-Forward Validator
Runs all three models across all chronological folds.
No test data ever leaks into training. Gap of 14 days enforced between train_end and test_start.

Results stored to walk_forward_folds and model_metrics tables after each fold.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.datasets.training_dataset import TrainingDataset, DataSplit
from ml.models.lightgbm_model import LightGBMModel
from ml.models.xgboost_model import XGBoostModel
from ml.models.catboost_model import CatBoostModel
from ml.models.base_model import BaseModel
from ml.validation.metrics import compute_metrics, aggregate_fold_metrics

log = get_logger("walk_forward")

# Fraction of training fold used as early-stopping validation set
VAL_FRACTION = 0.15

MODEL_CLASSES = {
    "lightgbm": LightGBMModel,
    "xgboost":  XGBoostModel,
    "catboost": CatBoostModel,
}


def _split_train_val(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    val_fraction: float = VAL_FRACTION,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """
    Chronological train/validation split within a fold's training set.
    Last val_fraction rows become the early-stopping validation set.
    """
    n     = len(X_train)
    split = int(n * (1 - val_fraction))
    X_tr  = X_train.iloc[:split]
    y_tr  = y_train.iloc[:split]
    X_vl  = X_train.iloc[split:]
    y_vl  = y_train.iloc[split:]
    return X_tr, y_tr, X_vl, y_vl


def run_fold(
    fold: DataSplit,
    task: str,
    label_col: str,
    model_name: str,
    version: int = 1,
    save_fold_model: bool = False,
) -> dict:
    """
    Train one model on one fold and return metrics.

    Returns dict with:
      fold, model_name, task, train_rows, test_rows, metrics, trained_at
    """
    ModelClass = MODEL_CLASSES[model_name]
    model: BaseModel = ModelClass(task=task, label_col=label_col, version=version)

    X_tr, y_tr, X_vl, y_vl = _split_train_val(fold.X_train, fold.y_train)

    try:
        model.fit(X_tr, y_tr, X_vl, y_vl)
    except Exception as exc:
        log.error("Fold %d %s training failed: %s", fold.fold, model_name, exc)
        return {
            "fold": fold.fold, "model_name": model_name, "task": task,
            "error": str(exc), "metrics": {},
        }

    y_pred  = model.predict(fold.X_test)
    y_proba = model.predict_proba(fold.X_test)
    metrics = compute_metrics(fold.y_test, y_pred, y_proba, task)

    if save_fold_model:
        model.save(fold=fold.fold)

    result = {
        "fold":        fold.fold,
        "model_name":  model_name,
        "task":        task,
        "train_start": str(fold.train_start),
        "train_end":   str(fold.train_end),
        "test_start":  str(fold.test_start),
        "test_end":    str(fold.test_end),
        "train_rows":  len(fold.X_train),
        "test_rows":   len(fold.X_test),
        "metrics":     metrics,
        "trained_at":  datetime.utcnow().isoformat(),
    }
    log.info(
        "Fold %d | %s | task=%s | test_rows=%d | metrics=%s",
        fold.fold, model_name, task, len(fold.X_test),
        {k: round(v, 4) for k, v in metrics.items()},
    )
    return result


def run_walk_forward_validation(
    dataset: TrainingDataset,
    model_names: Optional[list[str]] = None,
    version: int = 1,
    save_to_db: bool = True,
) -> dict:
    """
    Run all folds for all models. Returns full results dict.

    Args:
        dataset:     Prepared TrainingDataset with .folds populated
        model_names: Subset of ["lightgbm", "xgboost", "catboost"] to run
        version:     Model version number for artifact naming
        save_to_db:  Whether to persist results to walk_forward_folds / model_metrics

    Returns:
        {
          "model_results": {model_name: [fold_result, ...]},
          "aggregated":    {model_name: {metric_mean/std/...}},
          "best_model":    str,
          "total_folds":   int,
        }
    """
    if model_names is None:
        model_names = list(MODEL_CLASSES.keys())

    if not dataset.folds:
        log.error("No folds in dataset — run prepare_training_dataset() first")
        return {"error": "no_folds"}

    task      = dataset.label_col
    is_classif = (task == "direction_5d" or task == "outperform_binary")
    ml_task   = "direction" if is_classif else "expected_return"

    all_results: dict[str, list[dict]] = {m: [] for m in model_names}

    for fold in dataset.folds:
        log.info("=== Fold %d: train %s to %s, test %s to %s ===",
                 fold.fold, fold.train_start, fold.train_end,
                 fold.test_start, fold.test_end)
        for model_name in model_names:
            result = run_fold(fold, ml_task, task, model_name, version)
            all_results[model_name].append(result)

    # Aggregate per model
    aggregated = {}
    for model_name, fold_results in all_results.items():
        fold_metrics = [r["metrics"] for r in fold_results if "metrics" in r and r["metrics"]]
        aggregated[model_name] = aggregate_fold_metrics(fold_metrics)

    # Determine best model by primary metric
    primary_key = "auc_roc_mean" if is_classif else "ic_mean"
    best_model  = max(
        aggregated.keys(),
        key=lambda m: aggregated[m].get(primary_key, -999),
    )

    if save_to_db:
        _persist_results(all_results, aggregated, version, ml_task)

    log.info("Walk-forward complete. Best model: %s (primary=%s)", best_model, primary_key)
    return {
        "model_results": all_results,
        "aggregated":    aggregated,
        "best_model":    best_model,
        "total_folds":   len(dataset.folds),
    }


def _persist_results(
    all_results: dict[str, list[dict]],
    aggregated:  dict[str, dict],
    version:     int,
    task:        str,
) -> None:
    """Persist walk-forward results to walk_forward_folds and model_metrics tables."""
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import WalkForwardFold, ModelMetric
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        with get_db() as db:
            for model_name, fold_results in all_results.items():
                for r in fold_results:
                    if "error" in r:
                        continue
                    stmt = sqlite_insert(WalkForwardFold).values(
                        model_name  = model_name,
                        task        = task,
                        version     = version,
                        fold        = r["fold"],
                        train_start = r["train_start"],
                        train_end   = r["train_end"],
                        test_start  = r["test_start"],
                        test_end    = r["test_end"],
                        train_rows  = r["train_rows"],
                        test_rows   = r["test_rows"],
                        status      = "complete",
                    ).on_conflict_do_update(
                        index_elements=["model_name", "task", "version", "fold"],
                        set_={
                            "train_start": r["train_start"],
                            "train_end":   r["train_end"],
                            "test_start":  r["test_start"],
                            "test_end":    r["test_end"],
                            "train_rows":  r["train_rows"],
                            "test_rows":   r["test_rows"],
                            "status":      "complete",
                        }
                    )
                    db.execute(stmt)

                    for metric_name, metric_val in r.get("metrics", {}).items():
                        db.add(ModelMetric(
                            model_name   = model_name,
                            task         = task,
                            version      = version,
                            fold         = r["fold"],
                            metric_name  = metric_name,
                            metric_value = float(metric_val),
                            split        = "test",
                            computed_at  = datetime.utcnow(),
                        ))

            db.commit()
            log.info("Walk-forward results persisted to DB")
    except Exception as exc:
        log.error("Failed to persist walk-forward results: %s", exc)

"""
Feature Importance Tracker
Reads feature importance from trained models and persists snapshots
to FeatureImportanceHistory.

LightGBM, XGBoost, CatBoost all expose feature_importances_ as arrays
aligned to the feature names list. This module extracts those arrays,
ranks by importance, and writes one row per feature per model/task/date.
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import FeatureImportanceHistory, ModelVersion, Prediction, FeatureValue
from aqrti.utils.logger import get_logger

log = get_logger("feature_importance_tracker")

MIN_IC_SAMPLES = 20


def _compute_ic_for_feature(
    db:           Session,
    feature_name: str,
    days:         int = 30,
) -> Optional[float]:
    """
    Spearman IC between a feature's value and subsequent actual return.
    Returns None if insufficient data.
    """
    from scipy.stats import spearmanr

    cutoff = date.today().__class__.today().__class__.fromisoformat(
        str(date.today())
    )
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)

    rows = (
        db.query(FeatureValue.value, Prediction.actual_return)
        .join(Prediction, (FeatureValue.symbol == Prediction.symbol) &
              (FeatureValue.date == Prediction.date))
        .filter(
            FeatureValue.feature_name == feature_name,
            FeatureValue.date >= cutoff,
            Prediction.actual_return.isnot(None),
        )
        .all()
    )

    if len(rows) < MIN_IC_SAMPLES:
        return None

    vals    = [r[0] for r in rows if r[0] is not None]
    returns = [r[1] for r in rows if r[0] is not None]
    if len(vals) < MIN_IC_SAMPLES:
        return None

    result = spearmanr(vals, returns)
    ic     = float(result.correlation)
    return round(ic, 6) if not np.isnan(ic) else None


def record_importance_snapshot(
    db:           Session,
    model_name:   str,
    task:         str,
    version:      str,
    feature_names: list[str],
    importances:  list[float],
    today:        Optional[date] = None,
) -> int:
    """
    Write one FeatureImportanceHistory row per feature.
    Returns count of rows written.
    """
    today = today or date.today()
    if len(feature_names) != len(importances):
        log.error("feature_names/importances length mismatch: %d vs %d",
                  len(feature_names), len(importances))
        return 0

    # Normalise importances to [0, 1]
    arr    = np.array(importances, dtype=float)
    total  = arr.sum()
    if total > 0:
        arr = arr / total

    # Rank by importance (1 = most important)
    ranks = len(arr) - arr.argsort().argsort()

    written = 0
    for feat, imp, rank in zip(feature_names, arr.tolist(), ranks.tolist()):
        # Skip if already recorded today
        existing = (
            db.query(FeatureImportanceHistory.id)
            .filter(
                FeatureImportanceHistory.feature_name == feat,
                FeatureImportanceHistory.model_name   == model_name,
                FeatureImportanceHistory.task          == task,
                FeatureImportanceHistory.measured_date == today,
            )
            .first()
        )
        if existing:
            continue

        ic = _compute_ic_for_feature(db, feat, days=30)
        row = FeatureImportanceHistory(
            feature_name  = feat,
            model_name    = model_name,
            task          = task,
            version       = version,
            measured_date = today,
            importance    = round(float(imp), 8),
            rank          = int(rank),
            ic            = ic,
        )
        db.add(row)
        written += 1

    log.info("Importance snapshot: model=%s task=%s features=%d written=%d",
             model_name, task, len(feature_names), written)
    return written


def get_top_features(
    db:         Session,
    model_name: Optional[str] = None,
    task:       Optional[str] = None,
    top_n:      int = 20,
    days:       int = 30,
) -> list[dict]:
    """
    Return the top N features by average importance over the last N days.
    """
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    q = db.query(FeatureImportanceHistory).filter(
        FeatureImportanceHistory.measured_date >= cutoff,
    )
    if model_name:
        q = q.filter(FeatureImportanceHistory.model_name == model_name)
    if task:
        q = q.filter(FeatureImportanceHistory.task == task)

    rows = q.all()
    by_feat: dict[str, list[float]] = {}
    ic_by_feat: dict[str, list[float]] = {}
    for r in rows:
        by_feat.setdefault(r.feature_name, []).append(r.importance)
        if r.ic is not None:
            ic_by_feat.setdefault(r.feature_name, []).append(r.ic)

    results = [
        {
            "feature_name":    feat,
            "avg_importance":  round(sum(vals) / len(vals), 6),
            "avg_ic":          round(sum(ic_by_feat[feat]) / len(ic_by_feat[feat]), 6)
                               if feat in ic_by_feat else None,
            "observations":    len(vals),
        }
        for feat, vals in by_feat.items()
    ]
    results.sort(key=lambda x: x["avg_importance"], reverse=True)
    return results[:top_n]


def get_importance_summary(db: Session, days: int = 30) -> dict:
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    rows   = db.query(FeatureImportanceHistory).filter(
        FeatureImportanceHistory.measured_date >= cutoff,
    ).all()
    total  = len(rows)
    with_ic = sum(1 for r in rows if r.ic is not None)
    return {
        "days":          days,
        "total_records": total,
        "features_with_ic": with_ic,
        "unique_features": len({r.feature_name for r in rows}),
        "unique_models":   len({r.model_name for r in rows}),
    }

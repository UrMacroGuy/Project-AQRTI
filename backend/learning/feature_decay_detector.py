"""
Feature Decay Detector
Measures whether a feature's predictive power is degrading over time.

For each feature it computes IC over 30d / 90d / 180d rolling windows,
then fits a linear trend (slope) to detect decay direction.
Results are written to FeatureDecayHistory.

Decay severity thresholds:
  none     → |ic_30d| >= 0.05 (still predictive)
  mild     → ic_30d in [0.02, 0.05)
  moderate → ic_30d in [0.01, 0.02)
  severe   → ic_30d < 0.01 or negative
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

import numpy as np
from scipy.stats import spearmanr, linregress
from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import FeatureValue, Prediction, FeatureDecayHistory
from aqrti.utils.logger import get_logger

log = get_logger("feature_decay_detector")

MIN_SAMPLES = 15

DECAY_THRESHOLDS = {
    "none":     0.05,
    "mild":     0.02,
    "moderate": 0.01,
    "severe":   0.0,
}


def _ic_for_window(
    db:           Session,
    feature_name: str,
    days:         int,
) -> Optional[float]:
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(FeatureValue.value, Prediction.actual_return)
        .join(
            Prediction,
            (FeatureValue.symbol == Prediction.symbol) &
            (FeatureValue.date   == Prediction.date),
        )
        .filter(
            FeatureValue.feature_name == feature_name,
            FeatureValue.date         >= cutoff,
            Prediction.actual_return.isnot(None),
        )
        .all()
    )
    if len(rows) < MIN_SAMPLES:
        return None
    feat_vals = [r[0] for r in rows if r[0] is not None]
    ret_vals  = [r[1] for r in rows if r[0] is not None]
    if len(feat_vals) < MIN_SAMPLES:
        return None
    result = spearmanr(feat_vals, ret_vals)
    ic     = float(result.correlation)
    return round(ic, 6) if not np.isnan(ic) else None


def _decay_severity(ic_30d: Optional[float]) -> str:
    if ic_30d is None:
        return "moderate"
    abs_ic = abs(ic_30d)
    if abs_ic >= DECAY_THRESHOLDS["none"]:
        return "none"
    if abs_ic >= DECAY_THRESHOLDS["mild"]:
        return "mild"
    if abs_ic >= DECAY_THRESHOLDS["moderate"]:
        return "moderate"
    return "severe"


def _ic_trend(ic_30d, ic_90d, ic_180d) -> Optional[float]:
    """
    Linear slope fitted to [180d, 90d, 30d] IC values.
    Negative slope = decay; positive = improvement.
    Returns None if not enough valid points.
    """
    points = [(180, ic_180d), (90, ic_90d), (30, ic_30d)]
    valid  = [(x, y) for x, y in points if y is not None]
    if len(valid) < 2:
        return None
    xs    = [p[0] for p in valid]
    ys    = [p[1] for p in valid]
    slope, *_ = linregress(xs, ys)
    return round(float(slope), 8)


def detect_decay_for_feature(
    db:           Session,
    feature_name: str,
    today:        Optional[date] = None,
) -> Optional[FeatureDecayHistory]:
    """
    Compute decay metrics for a single feature and write to DB.
    Returns None if already recorded today or insufficient data.
    """
    today = today or date.today()

    existing = (
        db.query(FeatureDecayHistory.id)
        .filter(
            FeatureDecayHistory.feature_name  == feature_name,
            FeatureDecayHistory.measured_date == today,
        )
        .first()
    )
    if existing:
        return None

    ic_30  = _ic_for_window(db, feature_name, 30)
    ic_90  = _ic_for_window(db, feature_name, 90)
    ic_180 = _ic_for_window(db, feature_name, 180)

    if ic_30 is None and ic_90 is None and ic_180 is None:
        log.debug("No IC data for feature %s — skipping", feature_name)
        return None

    trend    = _ic_trend(ic_30, ic_90, ic_180)
    severity = _decay_severity(ic_30)
    flag     = severity in ("moderate", "severe")

    row = FeatureDecayHistory(
        feature_name  = feature_name,
        measured_date = today,
        ic_30d        = ic_30,
        ic_90d        = ic_90,
        ic_180d       = ic_180,
        ic_trend      = trend,
        decay_flag    = flag,
        decay_severity= severity,
    )
    db.add(row)
    log.info(
        "Decay: %s ic30=%.4f ic90=%.4f severity=%s flag=%s",
        feature_name,
        ic_30 or 0, ic_90 or 0, severity, flag,
    )
    return row


def run_decay_detection(db: Session, feature_names: Optional[list[str]] = None) -> dict:
    """
    Run decay detection for all features or a specified list.
    If feature_names is None, derives the list from FeatureValue table.
    """
    if feature_names is None:
        rows = db.query(FeatureValue.feature_name).distinct().all()
        feature_names = [r[0] for r in rows]

    recorded = 0
    skipped  = 0
    flagged  = []

    for feat in feature_names:
        row = detect_decay_for_feature(db, feat)
        if row is None:
            skipped += 1
        else:
            recorded += 1
            if row.decay_flag:
                flagged.append({"feature": feat, "severity": row.decay_severity, "ic_30d": row.ic_30d})

    db.commit()
    log.info("Decay detection done: recorded=%d skipped=%d flagged=%d", recorded, skipped, len(flagged))
    return {
        "features_processed": len(feature_names),
        "recorded":           recorded,
        "skipped":            skipped,
        "flagged":            flagged,
    }


def get_decay_summary(db: Session, days: int = 30) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows   = db.query(FeatureDecayHistory).filter(
        FeatureDecayHistory.measured_date >= cutoff,
    ).all()

    by_severity = {"none": 0, "mild": 0, "moderate": 0, "severe": 0}
    for r in rows:
        by_severity[r.decay_severity or "moderate"] = by_severity.get(r.decay_severity or "moderate", 0) + 1

    flagged = [r for r in rows if r.decay_flag]
    return {
        "days":         days,
        "total":        len(rows),
        "flagged":      len(flagged),
        "by_severity":  by_severity,
        "flagged_features": [
            {"feature": r.feature_name, "severity": r.decay_severity,
             "ic_30d": r.ic_30d, "ic_trend": r.ic_trend}
            for r in sorted(flagged, key=lambda x: x.ic_30d or 0)
        ],
    }

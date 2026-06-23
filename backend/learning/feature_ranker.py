"""
Feature Ranker
Combines importance scores, IC, and decay status into a unified feature ranking.

Composite score per feature (0-100):
  - Importance score       40%  (normalised from FeatureImportanceHistory)
  - IC quality             35%  (abs IC 30d, clipped to [0, 0.15])
  - Decay health           25%  (100 if no decay, 60 mild, 30 moderate, 0 severe)

Features are ranked and tagged with recommendations for the architect.
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import FeatureImportanceHistory, FeatureDecayHistory
from aqrti.utils.logger import get_logger

log = get_logger("feature_ranker")

DECAY_HEALTH = {"none": 100, "mild": 60, "moderate": 30, "severe": 0}
IC_CLIP_MAX  = 0.15   # IC above this is treated as 0.15 for scoring


def _get_importance_map(db: Session, days: int) -> dict[str, float]:
    """Average normalised importance per feature over the last N days."""
    cutoff = date.today() - timedelta(days=days)
    rows   = db.query(FeatureImportanceHistory).filter(
        FeatureImportanceHistory.measured_date >= cutoff,
    ).all()
    by_feat: dict[str, list[float]] = {}
    for r in rows:
        by_feat.setdefault(r.feature_name, []).append(r.importance or 0.0)
    return {k: sum(v) / len(v) for k, v in by_feat.items()}


def _get_decay_map(db: Session, days: int) -> dict[str, dict]:
    """Latest decay record per feature."""
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(FeatureDecayHistory)
        .filter(FeatureDecayHistory.measured_date >= cutoff)
        .order_by(FeatureDecayHistory.feature_name, FeatureDecayHistory.measured_date.desc())
        .all()
    )
    seen   = set()
    result = {}
    for r in rows:
        if r.feature_name not in seen:
            result[r.feature_name] = {
                "ic_30d":        r.ic_30d,
                "ic_trend":      r.ic_trend,
                "decay_flag":    r.decay_flag,
                "decay_severity": r.decay_severity or "none",
            }
            seen.add(r.feature_name)
    return result


def _composite_score(
    importance:  float,
    max_imp:     float,
    ic_30d:      Optional[float],
    decay_sev:   str,
) -> float:
    # Importance score: normalised relative to max in dataset
    imp_score = (importance / max_imp * 100) if max_imp > 0 else 50.0
    imp_score = min(100.0, imp_score)

    # IC score: absolute IC clipped to IC_CLIP_MAX, mapped to 0-100
    abs_ic    = abs(ic_30d) if ic_30d is not None else 0.0
    ic_score  = min(abs_ic / IC_CLIP_MAX, 1.0) * 100

    # Decay health
    decay_score = float(DECAY_HEALTH.get(decay_sev, 30))

    composite = imp_score * 0.40 + ic_score * 0.35 + decay_score * 0.25
    return round(composite, 2)


def rank_features(
    db:         Session,
    model_name: Optional[str] = None,
    task:       Optional[str] = None,
    days:       int = 30,
) -> list[dict]:
    """
    Return all features ranked by composite score (highest first).
    Each entry includes recommendation tag.
    """
    imp_map   = _get_importance_map(db, days)
    decay_map = _get_decay_map(db, days)

    if not imp_map:
        log.info("No importance data available for ranking")
        return []

    max_imp   = max(imp_map.values()) or 1.0
    all_feats = set(imp_map) | set(decay_map)

    results = []
    for feat in all_feats:
        imp        = imp_map.get(feat, 0.0)
        decay_info = decay_map.get(feat, {"ic_30d": None, "decay_severity": "none",
                                           "decay_flag": False, "ic_trend": None})
        ic_30d     = decay_info["ic_30d"]
        decay_sev  = decay_info["decay_severity"]

        score = _composite_score(imp, max_imp, ic_30d, decay_sev)
        rec   = _recommendation(score, decay_sev, ic_30d, decay_info["decay_flag"])

        results.append({
            "feature_name":    feat,
            "composite_score": score,
            "importance":      round(imp, 6),
            "ic_30d":          ic_30d,
            "ic_trend":        decay_info["ic_trend"],
            "decay_severity":  decay_sev,
            "decay_flag":      decay_info["decay_flag"],
            "recommendation":  rec,
        })

    results.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    log.info("Feature ranking complete: %d features ranked", len(results))
    return results


def _recommendation(score: float, severity: str, ic_30d: Optional[float], flag: bool) -> str:
    if severity == "severe":
        return "RETIRE: Feature has lost predictive power. Consider removing."
    if severity == "moderate" and flag:
        return "REVIEW: Moderate decay detected. Monitor over next 30 days."
    if score >= 70:
        return "KEEP: Strong feature. High importance and good IC."
    if score >= 50:
        return "MONITOR: Adequate performance. Watch for decay."
    if ic_30d is not None and abs(ic_30d) < 0.02:
        return "REPLACE: Low IC. Consider feature engineering alternatives."
    return "WATCH: Below-average composite score."


def get_ranking_summary(db: Session, days: int = 30) -> dict:
    ranked = rank_features(db, days=days)
    if not ranked:
        return {"total": 0, "by_recommendation": {}}
    by_rec: dict[str, int] = {}
    for r in ranked:
        tag = r["recommendation"].split(":")[0]
        by_rec[tag] = by_rec.get(tag, 0) + 1
    return {
        "total":            len(ranked),
        "top_5":            ranked[:5],
        "bottom_5":         ranked[-5:],
        "by_recommendation": by_rec,
        "days":             days,
    }

"""
AQRTI Confidence Engine
Fuses 5 independent signals into a single 0–100 confidence score with category label.

Inputs:
  1. Model Agreement     — how much do the 3 models agree? (from ensemble)
  2. Historical Accuracy — how accurate has this task been on test folds?
  3. Regime Confidence   — how certain is the market regime detection?
  4. Signal Strength     — distance of direction_prob from 0.5 (conviction)
  5. Feature Completeness — what fraction of features are non-null?

Output:
  confidence_score:    0–100
  confidence_category: "Exceptional" | "Strong" | "Good" | "Weak" | "Ignore"
  component_scores:    dict of each input's contribution

Categories:
  Exceptional: 80–100
  Strong:      65–79
  Good:        50–64
  Weak:        35–49
  Ignore:      0–34
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np

from aqrti.utils.logger import get_logger

log = get_logger("confidence_engine")

# Component weights (must sum to 1.0)
COMPONENT_WEIGHTS = {
    "model_agreement":     0.30,
    "historical_accuracy": 0.25,
    "regime_confidence":   0.20,
    "signal_strength":     0.15,
    "feature_completeness": 0.10,
}

# Category thresholds
CATEGORIES = [
    (80, "Exceptional"),
    (65, "Strong"),
    (50, "Good"),
    (35, "Weak"),
    (0,  "Ignore"),
]


def _category(score: float) -> str:
    for threshold, label in CATEGORIES:
        if score >= threshold:
            return label
    return "Ignore"


def compute_confidence(
    model_agreement:      float,       # 0.0–1.0 from ensemble
    direction_prob:       float,       # 0.0–1.0 from ensemble
    feature_completeness: float,       # 0.0–1.0 (fraction non-null features)
    regime_confidence:    float = 0.5, # 0.0–1.0 from market_regimes table
    historical_accuracy:  float = 0.5, # 0.0–1.0 from walk-forward metrics
) -> dict:
    """
    Compute confidence score from 5 inputs.

    All inputs are normalized to 0–1 before weighting.
    Returns dict with score (0–100), category, and component breakdown.
    """
    # Normalize each component to 0–1

    # 1. Model agreement: already 0–1
    c_agreement = float(np.clip(model_agreement, 0.0, 1.0))

    # 2. Historical accuracy: already 0–1 (e.g., AUC or IC normalized)
    c_historical = float(np.clip(historical_accuracy, 0.0, 1.0))

    # 3. Regime confidence: already 0–1
    c_regime = float(np.clip(regime_confidence, 0.0, 1.0))

    # 4. Signal strength: abs(prob - 0.5) * 2 maps [0.5, 1.0] → [0, 1]
    c_signal = float(np.clip(abs(direction_prob - 0.5) * 2.0, 0.0, 1.0))

    # 5. Feature completeness: already 0–1
    c_features = float(np.clip(feature_completeness, 0.0, 1.0))

    components = {
        "model_agreement":     c_agreement,
        "historical_accuracy": c_historical,
        "regime_confidence":   c_regime,
        "signal_strength":     c_signal,
        "feature_completeness": c_features,
    }

    # Weighted sum → 0–100
    raw_score = sum(
        COMPONENT_WEIGHTS[k] * v for k, v in components.items()
    )
    score = float(np.clip(raw_score * 100.0, 0.0, 100.0))
    category = _category(score)

    return {
        "confidence_score":    round(score, 2),
        "confidence_category": category,
        "component_scores":    {k: round(v * 100, 2) for k, v in components.items()},
        "weights":             COMPONENT_WEIGHTS,
    }


def get_historical_accuracy(task: str, version: int = 1) -> float:
    """
    Load average accuracy metric from latest walk-forward folds for this task.
    Returns 0.5 (no-skill baseline) if no data available.
    """
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import ModelMetric

        primary = "auc_roc" if task == "direction" else "ic"

        with get_db() as db:
            rows = (
                db.query(ModelMetric.metric_value)
                .filter_by(task=task, metric_name=primary, split="test", version=version)
                .order_by(ModelMetric.computed_at.desc())
                .limit(12)   # last 4 folds × 3 models
                .all()
            )

        if not rows:
            return 0.5

        values = [float(r[0]) for r in rows]
        avg    = float(np.mean(values))

        # Normalize: AUC is already 0–1; IC maps -1..1 to 0..1
        if primary == "ic":
            avg = (avg + 1.0) / 2.0
        return float(np.clip(avg, 0.0, 1.0))

    except Exception as exc:
        log.debug("get_historical_accuracy failed: %s", exc)
        return 0.5


def get_regime_confidence() -> float:
    """
    Load the most recent market regime confidence from the market_regimes table.
    Returns 0.5 if unavailable.
    """
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import MarketRegime

        with get_db() as db:
            row = (
                db.query(MarketRegime.confidence)
                .order_by(MarketRegime.date.desc())
                .first()
            )
        if row and row[0] is not None:
            return float(np.clip(row[0] / 100.0, 0.0, 1.0))
        return 0.5
    except Exception:
        return 0.5


def compute_feature_completeness(features: dict[str, float], required_cols: list[str]) -> float:
    """
    Fraction of required feature columns that are non-null and non-NaN.
    """
    if not required_cols:
        return 1.0
    import math
    valid = sum(
        1 for col in required_cols
        if features.get(col) is not None and not math.isnan(features.get(col, float("nan")))
    )
    return valid / len(required_cols)


def score_prediction(
    symbol:           str,
    features:         dict[str, float],
    ensemble_result:  dict,
    required_cols:    list[str],
    version:          int = 1,
) -> dict:
    """
    Full confidence scoring pipeline for one prediction.

    Args:
        symbol:          NSE ticker
        features:        Feature dict from feature_store
        ensemble_result: Output of EnsembleEngine.predict_symbol()
        required_cols:   Feature columns the models expect
        version:         Model version

    Returns merged dict with confidence fields added.
    """
    task = "direction"   # primary task for accuracy lookup

    model_agreement      = ensemble_result.get("model_agreement", 0.5)
    direction_prob       = ensemble_result.get("direction_prob",   0.5)
    feature_completeness = compute_feature_completeness(features, required_cols)
    historical_accuracy  = get_historical_accuracy(task, version)
    regime_confidence    = get_regime_confidence()

    confidence = compute_confidence(
        model_agreement      = model_agreement,
        direction_prob       = direction_prob,
        feature_completeness = feature_completeness,
        regime_confidence    = regime_confidence,
        historical_accuracy  = historical_accuracy,
    )

    result = {**ensemble_result, **confidence}
    result["symbol"] = symbol
    return result

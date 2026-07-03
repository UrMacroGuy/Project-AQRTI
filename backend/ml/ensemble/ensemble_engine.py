"""
AQRTI Ensemble Engine
Combines CatBoost + NGBoost predictions using dynamic weights.

For each symbol, produces:
  - direction_prob:    probability of positive 5d return (0.0–1.0)
  - expected_return:   expected 5-day return (%)
  - outperform_prob:   probability of outperforming NIFTY (0.0–1.0)
  - direction:         "Bullish" | "Bearish" | "Neutral"
  - model_agreement:   0.0–1.0 (1.0 = all models agree)
"""

from __future__ import annotations

import sys
import os
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.ensemble.model_weighting import load_dynamic_weights, EQUAL_WEIGHTS
from ml.validation.backtest_validator import load_active_models
from ml.models.base_model import BaseModel

log = get_logger("ensemble_engine")

# Probability threshold for Bullish/Bearish classification
BULLISH_THRESHOLD = 0.55
BEARISH_THRESHOLD = 0.45


def _weighted_average(
    predictions: dict[str, float],
    weights: dict[str, float],
) -> float:
    """Compute weighted average of scalar predictions."""
    total_w = 0.0
    total   = 0.0
    for model_name, pred in predictions.items():
        w = weights.get(model_name, 1.0 / len(predictions))
        total   += w * pred
        total_w += w
    return total / total_w if total_w > 0 else 0.0


def _model_agreement(probas: list[float]) -> float:
    """
    Measure agreement across models.
    Agreement = 1 - normalized std of probabilities.
    Perfect agreement (all same) = 1.0; max disagreement = 0.0.
    """
    if len(probas) < 2:
        return 1.0
    arr = np.array(probas, dtype=float)
    # Std ranges 0 to 0.5 for probabilities; normalize
    agreement = 1.0 - (arr.std() / 0.5)
    return float(np.clip(agreement, 0.0, 1.0))


class EnsembleEngine:
    """
    Loads active models once and runs ensemble predictions.
    Thread-safe for read operations.
    """

    def __init__(self, version: int = 1):
        self.version = version
        self._models: dict[str, dict[str, BaseModel]] = {}   # {label_col: {model_name: model}}
        self._weights: dict[str, dict[str, float]] = {}      # {task: {model_name: weight}}
        self._loaded_at: Optional[datetime] = None

    def load(self) -> "EnsembleEngine":
        """Load all active models and their weights from DB/disk."""
        self._models  = load_active_models()
        self._weights = {
            "direction":       load_dynamic_weights("direction",       self.version),
            "expected_return": load_dynamic_weights("expected_return", self.version),
        }
        self._loaded_at = datetime.utcnow()
        log.info(
            "EnsembleEngine loaded: %d label tasks, weights=%s",
            len(self._models), self._weights,
        )
        return self

    def is_ready(self) -> bool:
        return bool(self._models) and self._loaded_at is not None

    def predict_symbol(
        self,
        symbol: str,
        features: dict[str, float],
    ) -> Optional[dict]:
        """
        Run ensemble prediction for one symbol.

        Args:
            symbol:   NSE ticker
            features: {feature_name: value} from feature_store

        Returns dict or None if models not loaded / features insufficient.
        """
        if not self.is_ready():
            log.warning("EnsembleEngine not loaded — call .load() first")
            return None

        if not features:
            return None

        # Build input row
        result = {
            "symbol":          symbol,
            "predicted_at":    datetime.utcnow().isoformat(),
        }

        # ── Direction (classification) ───────────────────────────
        dir_models = self._models.get("direction_5d", {})
        dir_weights = self._weights.get("direction", EQUAL_WEIGHTS)

        dir_probas: dict[str, float] = {}
        for model_name, model in dir_models.items():
            try:
                feat_df = _features_to_df(features, model._feature_cols)
                if feat_df is None:
                    continue
                prob = float(model.predict_proba(feat_df)[0])
                dir_probas[model_name] = prob
            except Exception as exc:
                log.debug("Direction predict failed (%s/%s): %s", symbol, model_name, exc)

        if dir_probas:
            direction_prob = _weighted_average(dir_probas, dir_weights)
            agreement      = _model_agreement(list(dir_probas.values()))
        else:
            direction_prob = 0.5
            agreement      = 0.0

        # ── Expected Return (regression) ────────────────────────
        ret_models  = self._models.get("expected_return", {})
        ret_weights = self._weights.get("expected_return", EQUAL_WEIGHTS)

        ret_preds: dict[str, float] = {}
        for model_name, model in ret_models.items():
            try:
                feat_df = _features_to_df(features, model._feature_cols)
                if feat_df is None:
                    continue
                pred = float(model.predict(feat_df)[0])
                ret_preds[model_name] = pred
            except Exception as exc:
                log.debug("Return predict failed (%s/%s): %s", symbol, model_name, exc)

        expected_return = _weighted_average(ret_preds, ret_weights) if ret_preds else 0.0

        # ── Outperformance (classification) ─────────────────────
        op_models  = self._models.get("outperform_binary", {})

        op_probas: dict[str, float] = {}
        for model_name, model in op_models.items():
            try:
                feat_df = _features_to_df(features, model._feature_cols)
                if feat_df is None:
                    continue
                prob = float(model.predict_proba(feat_df)[0])
                op_probas[model_name] = prob
            except Exception as exc:
                log.debug("Outperform predict failed (%s/%s): %s", symbol, model_name, exc)

        op_weights = self._weights.get("outperform_binary", EQUAL_WEIGHTS)
        outperform_prob = _weighted_average(op_probas, op_weights) if op_probas else direction_prob

        # ── Direction label ──────────────────────────────────────
        if direction_prob >= BULLISH_THRESHOLD:
            direction = "Bullish"
        elif direction_prob <= BEARISH_THRESHOLD:
            direction = "Bearish"
        else:
            direction = "Neutral"

        result.update({
            "direction_prob":   round(direction_prob, 4),
            "expected_return":  round(expected_return, 4),
            "outperform_prob":  round(outperform_prob, 4),
            "direction":        direction,
            "model_agreement":  round(agreement, 4),
            "models_used": {
                "direction":    list(dir_probas.keys()),
                "return":       list(ret_preds.keys()),
                "outperform":   list(op_probas.keys()),
            },
        })
        return result

    def predict_universe(
        self,
        features_by_symbol: dict[str, dict[str, float]],
    ) -> list[dict]:
        """
        Run ensemble prediction for all symbols.

        Args:
            features_by_symbol: {symbol: {feature_name: value}}

        Returns list of prediction dicts.
        """
        results = []
        for symbol, features in features_by_symbol.items():
            pred = self.predict_symbol(symbol, features)
            if pred:
                results.append(pred)
        return results


def _features_to_df(
    features: dict[str, float],
    required_cols: list[str],
) -> Optional[pd.DataFrame]:
    """
    Build a single-row DataFrame from feature dict, aligned to model's required columns.
    Returns None if too many required features are missing.
    """
    row = {}
    missing = 0
    for col in required_cols:
        val = features.get(col)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            row[col] = 0.0   # fill with 0 (same as training median fill)
            missing += 1
        else:
            row[col] = val

    # More than 30% missing → unreliable prediction
    if missing / max(len(required_cols), 1) > 0.30:
        return None

    return pd.DataFrame([row], columns=required_cols)


# Module-level singleton — loaded once when prediction pipeline runs
_engine: Optional[EnsembleEngine] = None


def get_ensemble_engine(version: int = 1) -> EnsembleEngine:
    """Return the loaded singleton EnsembleEngine, loading if necessary."""
    global _engine
    if _engine is None or not _engine.is_ready():
        _engine = EnsembleEngine(version=version).load()
    return _engine


def reload_ensemble(version: int = 1) -> EnsembleEngine:
    """Force reload of all models (call after retraining)."""
    global _engine
    _engine = EnsembleEngine(version=version).load()
    return _engine

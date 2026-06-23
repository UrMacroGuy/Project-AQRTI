"""
AQRTI Regime Model Selector — Phase 8.5C
Automatically selects the most appropriate regime model for the current market regime.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Any

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger
from ml.regime_models.bull_model import BullRegimeModel
from ml.regime_models.bear_model import BearRegimeModel
from ml.regime_models.recovery_model import RecoveryRegimeModel
from ml.regime_models.rotation_model import RotationRegimeModel
from ml.regime_models.volatility_model import VolatilityRegimeModel
from ml.regime_models.base_regime_model import BaseRegimeModel

logger = get_logger("regime_model_selector")


REGIME_TO_MODEL: Dict[str, str] = {
    "BULL": "bull",
    "BULL_EXPANSION": "bull",
    "BULL_EXHAUSTION": "bull",
    "BEAR": "bear",
    "BEAR_EXPANSION": "bear",
    "BEAR_CAPITULATION": "bear",
    "RECOVERY": "recovery",
    "SECTOR_ROTATION": "rotation",
    "HIGH_VOLATILITY": "volatility_high",
    "LOW_VOLATILITY": "volatility_low",
    "VOLATILE": "volatility_high",
    "SIDEWAYS": "recovery",
}

_MODEL_CACHE: Dict[str, BaseRegimeModel] = {}


def get_model_for_regime(regime_name: str, task: str = "direction") -> BaseRegimeModel:
    """Return the appropriate regime model for a given regime label."""
    model_type = REGIME_TO_MODEL.get(regime_name.upper(), "bull")
    cache_key = f"{model_type}_{task}"

    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    model: BaseRegimeModel
    if model_type == "bull":
        model = BullRegimeModel(task)
    elif model_type == "bear":
        model = BearRegimeModel(task)
    elif model_type == "recovery":
        model = RecoveryRegimeModel(task)
    elif model_type == "rotation":
        model = RotationRegimeModel(task)
    elif model_type == "volatility_high":
        model = VolatilityRegimeModel(task, vol_type="high")
    elif model_type == "volatility_low":
        model = VolatilityRegimeModel(task, vol_type="low")
    else:
        model = BullRegimeModel(task)

    model.load()
    _MODEL_CACHE[cache_key] = model
    logger.info("Selected model '%s' for regime '%s'", model_type, regime_name)
    return model


def get_current_regime(db=None) -> str:
    """Query the database for the most recent regime classification."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        row = db.execute(
            "SELECT regime FROM market_regimes ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return row.regime if row else "BULL"
    finally:
        if own_session:
            db.close()


def predict_with_regime_model(
    X,
    regime: Optional[str] = None,
    task: str = "direction",
    db=None,
) -> Dict[str, Any]:
    """Run prediction using the model most appropriate for the current/given regime."""
    if regime is None:
        regime = get_current_regime(db)

    model = get_model_for_regime(regime, task)

    if not model.is_trained:
        logger.warning("Regime model for '%s' not yet trained. No prediction.", regime)
        return {"regime": regime, "model_type": model.regime_name, "status": "not_trained"}

    preds = model.predict(X)
    proba = model.predict_proba(X)

    result: Dict[str, Any] = {
        "regime": regime,
        "model_type": model.regime_name,
        "predictions": preds.tolist(),
    }
    if proba is not None:
        result["probabilities"] = proba.tolist()

    return result


def reload_all_regime_models():
    """Force reload all cached regime models from disk."""
    global _MODEL_CACHE
    _MODEL_CACHE = {}
    logger.info("All regime model cache cleared.")

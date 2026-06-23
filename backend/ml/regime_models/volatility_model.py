"""Volatility regime model — Phase 8.5C. Trained on HIGH_VOLATILITY + LOW_VOLATILITY data."""
from __future__ import annotations
from typing import Any
from ml.regime_models.base_regime_model import BaseRegimeModel


class VolatilityRegimeModel(BaseRegimeModel):
    """
    Specialist model for extreme volatility environments.
    Sub-task: 'high' or 'low' volatility can be specified via task kwarg.
    """

    def __init__(self, task: str = "direction", vol_type: str = "high"):
        super().__init__(f"VOLATILITY_{vol_type.upper()}", task)
        self.vol_type = vol_type

    def _build_model(self) -> Any:
        try:
            from lightgbm import LGBMClassifier, LGBMRegressor
            # High-vol: deeper trees to capture complex dynamics; low-vol: simpler
            depth = 7 if self.vol_type == "high" else 5
            leaves = 40 if self.vol_type == "high" else 20
            if self.task == "direction":
                return LGBMClassifier(
                    n_estimators=350, learning_rate=0.02, max_depth=depth,
                    num_leaves=leaves, min_child_samples=10,
                    reg_alpha=0.15, reg_lambda=0.25,
                    class_weight="balanced", random_state=42, verbose=-1,
                )
            return LGBMRegressor(
                n_estimators=350, learning_rate=0.02, max_depth=depth,
                num_leaves=leaves, min_child_samples=10,
                reg_alpha=0.15, reg_lambda=0.25,
                random_state=42, verbose=-1,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
            if self.task == "direction":
                return GradientBoostingClassifier(n_estimators=200, random_state=42)
            return GradientBoostingRegressor(n_estimators=200, random_state=42)

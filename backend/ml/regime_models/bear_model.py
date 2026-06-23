"""Bear regime model — Phase 8.5C. Trained on BEAR_EXPANSION + BEAR_CAPITULATION data."""
from __future__ import annotations
from typing import Any
from ml.regime_models.base_regime_model import BaseRegimeModel


class BearRegimeModel(BaseRegimeModel):
    """Specialist model for bear market conditions. Emphasizes downside prediction."""

    def __init__(self, task: str = "direction"):
        super().__init__("BEAR", task)

    def _build_model(self) -> Any:
        try:
            from lightgbm import LGBMClassifier, LGBMRegressor
            if self.task == "direction":
                return LGBMClassifier(
                    n_estimators=300, learning_rate=0.02, max_depth=5,
                    num_leaves=20, min_child_samples=15,
                    reg_alpha=0.2, reg_lambda=0.3,
                    class_weight="balanced", random_state=42, verbose=-1,
                )
            return LGBMRegressor(
                n_estimators=300, learning_rate=0.02, max_depth=5,
                num_leaves=20, min_child_samples=15,
                reg_alpha=0.2, reg_lambda=0.3,
                random_state=42, verbose=-1,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
            if self.task == "direction":
                return GradientBoostingClassifier(n_estimators=200, random_state=42)
            return GradientBoostingRegressor(n_estimators=200, random_state=42)

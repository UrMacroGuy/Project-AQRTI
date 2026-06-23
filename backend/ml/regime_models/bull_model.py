"""Bull regime model — Phase 8.5C. Trained on BULL_EXPANSION + BULL_EXHAUSTION data."""
from __future__ import annotations
from typing import Any
from ml.regime_models.base_regime_model import BaseRegimeModel


class BullRegimeModel(BaseRegimeModel):
    """Specialist model for bull market conditions."""

    def __init__(self, task: str = "direction"):
        super().__init__("BULL", task)

    def _build_model(self) -> Any:
        try:
            from lightgbm import LGBMClassifier, LGBMRegressor
            if self.task == "direction":
                return LGBMClassifier(
                    n_estimators=300, learning_rate=0.03, max_depth=6,
                    num_leaves=31, min_child_samples=20,
                    reg_alpha=0.1, reg_lambda=0.2,
                    class_weight="balanced", random_state=42, verbose=-1,
                )
            return LGBMRegressor(
                n_estimators=300, learning_rate=0.03, max_depth=6,
                num_leaves=31, min_child_samples=20,
                reg_alpha=0.1, reg_lambda=0.2,
                random_state=42, verbose=-1,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
            if self.task == "direction":
                return GradientBoostingClassifier(n_estimators=200, random_state=42)
            return GradientBoostingRegressor(n_estimators=200, random_state=42)

"""Recovery regime model — Phase 8.5C. Trained on RECOVERY regime data."""
from __future__ import annotations
from typing import Any
from ml.regime_models.base_regime_model import BaseRegimeModel


class RecoveryRegimeModel(BaseRegimeModel):
    """Specialist model for post-bear recovery phases."""

    def __init__(self, task: str = "direction"):
        super().__init__("RECOVERY", task)

    def _build_model(self) -> Any:
        try:
            from xgboost import XGBClassifier, XGBRegressor
            if self.task == "direction":
                return XGBClassifier(
                    n_estimators=250, learning_rate=0.04, max_depth=5,
                    reg_alpha=0.1, reg_lambda=0.2,
                    scale_pos_weight=1.0, random_state=42,
                    eval_metric="logloss", verbosity=0,
                )
            return XGBRegressor(
                n_estimators=250, learning_rate=0.04, max_depth=5,
                reg_alpha=0.1, reg_lambda=0.2,
                random_state=42, verbosity=0,
            )
        except ImportError:
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
            if self.task == "direction":
                return RandomForestClassifier(n_estimators=200, random_state=42)
            return RandomForestRegressor(n_estimators=200, random_state=42)

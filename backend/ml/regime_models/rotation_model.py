"""Rotation regime model — Phase 8.5C. Trained on SECTOR_ROTATION regime data."""
from __future__ import annotations
from typing import Any
from ml.regime_models.base_regime_model import BaseRegimeModel


class RotationRegimeModel(BaseRegimeModel):
    """Specialist model for sector rotation environments. Favors sector-relative features."""

    def __init__(self, task: str = "direction"):
        super().__init__("ROTATION", task)

    def _build_model(self) -> Any:
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
            if self.task == "direction":
                return CatBoostClassifier(
                    iterations=300, learning_rate=0.04, depth=6,
                    l2_leaf_reg=3, auto_class_weights="Balanced",
                    random_seed=42, verbose=0,
                )
            return CatBoostRegressor(
                iterations=300, learning_rate=0.04, depth=6,
                l2_leaf_reg=3, random_seed=42, verbose=0,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
            if self.task == "direction":
                return GradientBoostingClassifier(n_estimators=200, random_state=42)
            return GradientBoostingRegressor(n_estimators=200, random_state=42)

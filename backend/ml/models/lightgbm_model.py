"""
AQRTI LightGBM Model
Gradient boosting via LightGBM for both classification and regression tasks.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.models.base_model import BaseModel

log = get_logger("lightgbm_model")


class LightGBMModel(BaseModel):

    @property
    def model_type(self) -> str:
        return "lightgbm"

    def _get_default_hyperparams(self) -> dict:
        base = {
            "n_estimators":      1000,
            "learning_rate":     0.05,
            "num_leaves":        31,
            "max_depth":         -1,
            "min_child_samples": 50,       # anti-overfit: min 50 samples per leaf
            "subsample":         0.8,
            "colsample_bytree":  0.8,
            "lambda_l1":         0.1,
            "lambda_l2":         0.1,
            "early_stopping_rounds": 50,
            "verbose":           -1,
            "n_jobs":            -1,
            "random_state":      42,
        }
        return base

    def _build_model(self):
        try:
            import lightgbm as lgb
        except ImportError:
            raise ImportError("lightgbm not installed. Run: pip install lightgbm")

        params = {k: v for k, v in self.hyperparams.items()
                  if k != "early_stopping_rounds"}

        if self._is_classification:
            return lgb.LGBMClassifier(objective="binary", **params)
        else:
            return lgb.LGBMRegressor(objective="regression_l1", **params)

    def _fit_impl(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
    ) -> None:
        early_rounds = self.hyperparams.get("early_stopping_rounds", 50)

        fit_kwargs: dict = {}
        if X_val is not None and y_val is not None:
            fit_kwargs["eval_set"]     = [(X_val, y_val)]
            fit_kwargs["callbacks"]    = []
            try:
                import lightgbm as lgb
                fit_kwargs["callbacks"] = [
                    lgb.early_stopping(early_rounds, verbose=False),
                    lgb.log_evaluation(period=-1),
                ]
            except Exception:
                pass

        self._model.fit(X_train, y_train, **fit_kwargs)
        log.info(
            "LightGBM trained: task=%s rows=%d best_iter=%s",
            self.task, len(X_train),
            getattr(self._model, "best_iteration_", "n/a"),
        )

    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        return self._model.predict(X)

    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        if self._is_classification:
            proba = self._model.predict_proba(X)
            return proba[:, 1]   # probability of positive class
        return self._model.predict(X)

    def _feature_importance_impl(self) -> dict[str, float]:
        importances = self._model.feature_importances_
        return dict(zip(self._feature_cols, importances.tolist()))

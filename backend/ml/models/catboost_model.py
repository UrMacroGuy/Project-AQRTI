"""
AQRTI CatBoost Model
Gradient boosting via CatBoost for both classification and regression tasks.
CatBoost is less prone to overfitting on small datasets due to ordered boosting.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.models.base_model import BaseModel

log = get_logger("catboost_model")


class CatBoostModel(BaseModel):

    @property
    def model_type(self) -> str:
        return "catboost"

    def _get_default_hyperparams(self) -> dict:
        return {
            "iterations":        1000,
            "learning_rate":     0.05,
            "depth":             6,
            "min_data_in_leaf":  20,         # anti-overfit
            "l2_leaf_reg":       3.0,        # L2 regularization
            "subsample":         0.8,
            "colsample_bylevel": 0.8,
            "early_stopping_rounds": 50,
            "random_seed":       42,
            "verbose":           False,
            "allow_writing_files": False,    # suppress CatBoost temp file creation
        }

    def _build_model(self):
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
        except ImportError:
            raise ImportError("catboost not installed. Run: pip install catboost")

        params = {k: v for k, v in self.hyperparams.items()
                  if k != "early_stopping_rounds"}

        if self._is_classification:
            return CatBoostClassifier(
                loss_function="Logloss",
                eval_metric="AUC",
                auto_class_weights="Balanced",
                **params,
            )
        else:
            return CatBoostRegressor(loss_function="MAE", eval_metric="MAE", **params)

    def _fit_impl(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
    ) -> None:
        early_rounds = self.hyperparams.get("early_stopping_rounds", 50)

        fit_kwargs: dict = {"verbose": False}
        if X_val is not None and y_val is not None:
            try:
                from catboost import Pool
                fit_kwargs["eval_set"]            = Pool(X_val, y_val)
                fit_kwargs["early_stopping_rounds"] = early_rounds
            except Exception:
                fit_kwargs["eval_set"] = (X_val, y_val)

        self._model.fit(X_train, y_train, **fit_kwargs)
        log.info(
            "CatBoost trained: task=%s rows=%d best_iter=%s",
            self.task, len(X_train),
            getattr(self._model, "best_iteration_", "n/a"),
        )

    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        return self._model.predict(X)

    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        if self._is_classification:
            proba = self._model.predict_proba(X)
            return proba[:, 1]
        return self._model.predict(X)

    def _feature_importance_impl(self) -> dict[str, float]:
        importances = self._model.get_feature_importance()
        return dict(zip(self._feature_cols, importances.tolist()))

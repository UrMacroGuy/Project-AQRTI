"""
AQRTI XGBoost Model
Gradient boosting via XGBoost for both classification and regression tasks.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.models.base_model import BaseModel

log = get_logger("xgboost_model")


class XGBoostModel(BaseModel):

    @property
    def model_type(self) -> str:
        return "xgboost"

    def _get_default_hyperparams(self) -> dict:
        return {
            "n_estimators":          1000,
            "learning_rate":         0.05,
            "max_depth":             6,
            "min_child_weight":      10,      # anti-overfit: min sum of weights per child
            "subsample":             0.8,
            "colsample_bytree":      0.8,
            "reg_alpha":             0.1,     # L1 regularization
            "reg_lambda":            1.0,     # L2 regularization
            "early_stopping_rounds": 50,
            "verbosity":             0,
            "n_jobs":                -1,
            "random_state":          42,
            "eval_metric":           None,    # set dynamically in _build_model
        }

    def _build_model(self):
        try:
            import xgboost as xgb
        except ImportError:
            raise ImportError("xgboost not installed. Run: pip install xgboost")

        params = {k: v for k, v in self.hyperparams.items()
                  if k not in ("early_stopping_rounds", "eval_metric")}

        if self._is_classification:
            return xgb.XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                use_label_encoder=False,
                **params,
            )
        else:
            return xgb.XGBRegressor(
                objective="reg:absoluteerror",
                eval_metric="mae",
                **params,
            )

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
            fit_kwargs["eval_set"] = [(X_val, y_val)]

            # XGBoost 1.x uses early_stopping_rounds in fit(); 2.x uses it in constructor
            try:
                import xgboost as xgb
                ver = tuple(int(x) for x in xgb.__version__.split(".")[:2])
                if ver >= (2, 0):
                    # Already set via constructor in _build_model for v2
                    self._model.set_params(early_stopping_rounds=early_rounds)
                else:
                    fit_kwargs["early_stopping_rounds"] = early_rounds
            except Exception:
                fit_kwargs["early_stopping_rounds"] = early_rounds

        self._model.fit(X_train, y_train, **fit_kwargs)
        log.info(
            "XGBoost trained: task=%s rows=%d best_iter=%s",
            self.task, len(X_train),
            getattr(self._model, "best_iteration", "n/a"),
        )

    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        return self._model.predict(X)

    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        if self._is_classification:
            proba = self._model.predict_proba(X)
            return proba[:, 1]
        return self._model.predict(X)

    def _feature_importance_impl(self) -> dict[str, float]:
        importances = self._model.feature_importances_
        return dict(zip(self._feature_cols, importances.tolist()))

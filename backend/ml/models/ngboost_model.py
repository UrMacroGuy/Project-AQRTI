"""
AQRTI NGBoost Model
Probabilistic gradient boosting — predicts a full probability distribution,
not just a point estimate. For classification this means P(UP) with a
calibrated confidence interval, which the strategy backtester uses to
size positions (only trade when confidence > threshold).

Key advantage over CatBoost/LightGBM: confidence intervals let the system
skip low-confidence predictions rather than trading everything at 51%.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger
from ml.models.base_model import BaseModel

log = get_logger("ngboost_model")


class NGBoostModel(BaseModel):

    @property
    def model_type(self) -> str:
        return "ngboost"

    def _get_default_hyperparams(self) -> dict:
        return {
            "n_estimators":  500,
            "learning_rate": 0.05,
            "minibatch_frac": 0.8,    # stochastic training like subsample
            "col_sample":    0.8,     # feature subsampling per tree
            "natural_gradient": True,
            "verbose":       False,
            "random_state":  42,
        }

    def _build_model(self):
        try:
            from ngboost import NGBClassifier, NGBRegressor
            from ngboost.distns import Bernoulli, Normal
            from ngboost.scores import LogScore
        except ImportError:
            raise ImportError("ngboost not installed. Run: pip install ngboost")

        params = {
            "n_estimators":      self.hyperparams["n_estimators"],
            "learning_rate":     self.hyperparams["learning_rate"],
            "minibatch_frac":    self.hyperparams["minibatch_frac"],
            "col_sample":        self.hyperparams["col_sample"],
            "natural_gradient":  self.hyperparams["natural_gradient"],
            "verbose":           self.hyperparams["verbose"],
            "random_state":      self.hyperparams["random_state"],
        }

        if self._is_classification:
            return NGBClassifier(Dist=Bernoulli, Score=LogScore, **params)
        else:
            return NGBRegressor(Dist=Normal, Score=LogScore, **params)

    def _fit_impl(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
        sample_weight: Optional[np.ndarray] = None,
    ) -> None:
        fit_kwargs: dict = {}
        if X_val is not None and y_val is not None:
            fit_kwargs["X_val"] = X_val
            fit_kwargs["Y_val"] = y_val.values
            fit_kwargs["early_stopping_rounds"] = 50
        if sample_weight is not None:
            fit_kwargs["sample_weight"] = sample_weight

        self._model.fit(X_train, y_train.values, **fit_kwargs)
        best_iter = getattr(self._model, "best_val_loss_itr", None)
        log.info(
            "NGBoost trained: task=%s rows=%d best_iter=%s",
            self.task, len(X_train), best_iter,
        )

    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        if self._is_classification:
            # Returns class labels (0/1)
            return self._model.predict(X)
        return self._model.predict(X)

    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        if self._is_classification:
            # NGBClassifier.predict_proba returns shape [n, 2]; col 1 = P(UP)
            proba = self._model.predict_proba(X)
            return proba[:, 1]
        # Regression: return point predictions
        return self._model.predict(X)

    def predict_confidence_interval(
        self,
        X: pd.DataFrame,
        alpha: float = 0.90,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Return (lower, upper) confidence interval bounds.
        Only meaningful for regression task; for classification use predict_proba.
        alpha=0.90 → 90% CI.
        """
        X = X[self._feature_cols]
        dist = self._model.pred_dist(X)
        tail = (1 - alpha) / 2
        lower = dist.ppf(tail)
        upper = dist.ppf(1 - tail)
        return lower, upper

    def _feature_importance_impl(self) -> dict[str, float]:
        # NGBoost uses sklearn DecisionTree base learners; feature importances
        # are averaged across all estimators in the first stage (location param).
        try:
            importances = np.mean(
                [est.feature_importances_ for est in self._model.learners_[0]],
                axis=0,
            )
            return dict(zip(self._feature_cols, importances.tolist()))
        except Exception:
            # Fallback: equal weights
            n = len(self._feature_cols)
            return {col: 1.0 / n for col in self._feature_cols}

"""
AQRTI Base Model
Abstract interface that all ML models must implement.
Ensures consistent save/load, predict, and metrics API across LightGBM / XGBoost / CatBoost.
"""

from __future__ import annotations

import os
import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger

log = get_logger("base_model")

# Root directory for saved model artifacts
ML_MODELS_DIR = Path(__file__).parent.parent.parent / "ml_models"
ML_MODELS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ModelArtifact:
    """Metadata stored alongside every saved model."""
    model_type:    str
    task:          str          # "direction" | "expected_return" | "outperformance"
    label_col:     str
    version:       int
    feature_cols:  list[str]
    hyperparams:   dict[str, Any]
    train_rows:    int
    trained_at:    datetime
    fold_metrics:  list[dict]   = field(default_factory=list)
    final_metrics: dict         = field(default_factory=dict)
    feature_importance: dict    = field(default_factory=dict)


class BaseModel(ABC):
    """
    Abstract base for all AQRTI ML models.

    Subclasses must implement:
      - _build_model()  → the raw sklearn-compatible estimator
      - _get_default_hyperparams() → default hyperparams dict
      - model_type property → str identifier

    Subclasses inherit:
      - fit() with early stopping support
      - predict() / predict_proba()
      - save() / load()
      - feature_importance()
    """

    def __init__(
        self,
        task: str,
        label_col: str,
        hyperparams: Optional[dict] = None,
        version: int = 1,
    ):
        assert task in ("direction", "expected_return", "outperformance"), \
            f"Invalid task: {task}"
        self.task        = task
        self.label_col   = label_col
        self.version     = version
        self.hyperparams = {**self._get_default_hyperparams(), **(hyperparams or {})}
        self._model: Any = None
        self._feature_cols: list[str] = []
        self._artifact: Optional[ModelArtifact] = None
        self._is_classification = (task == "direction")

    @property
    @abstractmethod
    def model_type(self) -> str:
        """Identifier string: 'lightgbm' | 'xgboost' | 'catboost'"""
        ...

    @abstractmethod
    def _build_model(self) -> Any:
        """Build and return the underlying estimator (untrained)."""
        ...

    @abstractmethod
    def _get_default_hyperparams(self) -> dict:
        """Return default hyperparameters."""
        ...

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
    ) -> "BaseModel":
        """
        Train the model.
        If X_val/y_val provided, uses early stopping.
        """
        self._feature_cols = list(X_train.columns)
        self._model = self._build_model()
        self._fit_impl(X_train, y_train, X_val, y_val)
        return self

    @abstractmethod
    def _fit_impl(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
    ) -> None:
        """Model-specific training logic."""
        ...

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        For classification: returns class labels (0/1).
        For regression: returns predicted float values.
        """
        assert self._model is not None, "Model not trained — call fit() first"
        X = X[self._feature_cols]
        return self._predict_impl(X)

    @abstractmethod
    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        ...

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        For classification: returns probability of positive class (shape: [n,]).
        For regression: returns raw predictions (same as predict).
        """
        assert self._model is not None, "Model not trained"
        X = X[self._feature_cols]
        return self._predict_proba_impl(X)

    @abstractmethod
    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        ...

    def feature_importance(self) -> dict[str, float]:
        """Return {feature_name: importance_score} normalized to sum=1."""
        assert self._model is not None, "Model not trained"
        raw = self._feature_importance_impl()
        total = sum(raw.values())
        if total > 0:
            return {k: v / total for k, v in raw.items()}
        return raw

    @abstractmethod
    def _feature_importance_impl(self) -> dict[str, float]:
        ...

    def save(self, fold: Optional[int] = None) -> Path:
        """
        Save model artifact to ml_models/.
        Filename: {model_type}_{task}_v{version}[_fold{fold}].pkl
        """
        suffix  = f"_fold{fold}" if fold is not None else ""
        fname   = f"{self.model_type}_{self.task}_v{self.version}{suffix}.pkl"
        fpath   = ML_MODELS_DIR / fname

        payload = {
            "model":        self._model,
            "feature_cols": self._feature_cols,
            "artifact":     self._artifact,
            "hyperparams":  self.hyperparams,
            "task":         self.task,
            "label_col":    self.label_col,
            "version":      self.version,
        }
        with open(fpath, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

        log.info("Saved %s to %s", self.model_type, fpath)
        return fpath

    @classmethod
    def load(cls, path: Path) -> "BaseModel":
        """Load a saved model. Returns an instance with _model populated."""
        with open(path, "rb") as f:
            payload = pickle.load(f)

        instance = cls.__new__(cls)
        instance._model        = payload["model"]
        instance._feature_cols = payload["feature_cols"]
        instance._artifact     = payload.get("artifact")
        instance.hyperparams   = payload["hyperparams"]
        instance.task          = payload["task"]
        instance.label_col     = payload["label_col"]
        instance.version       = payload["version"]
        instance._is_classification = (instance.task == "direction")
        return instance

    def artifact_path(self, fold: Optional[int] = None) -> Path:
        suffix = f"_fold{fold}" if fold is not None else ""
        return ML_MODELS_DIR / f"{self.model_type}_{self.task}_v{self.version}{suffix}.pkl"

    def is_trained(self) -> bool:
        return self._model is not None

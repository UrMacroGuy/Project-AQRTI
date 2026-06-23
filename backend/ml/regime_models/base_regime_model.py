"""
Base class for all regime-specific models — Phase 8.5C.
Regime models are trained only on data from their target regime,
making them specialists rather than generalists.
"""

from __future__ import annotations

import json
import os
import pickle
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger

logger = get_logger("regime_model_base")

REGIME_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ml_models", "regime_models",
)


class BaseRegimeModel(ABC):
    """Abstract base for all regime-specific predictive models."""

    def __init__(self, regime_name: str, task: str = "direction"):
        self.regime_name = regime_name
        self.task = task
        self.model = None
        self.feature_names: List[str] = []
        self.metrics: Dict[str, float] = {}
        self.trained_at: Optional[datetime] = None
        self.is_trained = False
        self.artifact_path = os.path.join(
            REGIME_MODELS_DIR, f"{regime_name.lower()}_{task}.pkl"
        )

    @abstractmethod
    def _build_model(self) -> Any:
        """Instantiate the underlying ML model."""

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        feature_names: Optional[List[str]] = None,
        eval_set: Optional[Tuple[pd.DataFrame, pd.Series]] = None,
    ) -> Dict[str, float]:
        """Train the regime model. Returns training metrics."""
        if X.empty or len(y) < 20:
            logger.warning("[%s] Insufficient data: %d samples", self.regime_name, len(X))
            return {}

        self.feature_names = feature_names or list(X.columns)
        self.model = self._build_model()

        fit_kwargs: Dict[str, Any] = {}
        if eval_set is not None:
            try:
                fit_kwargs["eval_set"] = [eval_set]
                fit_kwargs["verbose"] = False
            except Exception:
                pass

        self.model.fit(X, y, **fit_kwargs)
        self.trained_at = datetime.utcnow()
        self.is_trained = True

        # Compute basic metrics on training set
        y_pred = self.model.predict(X)
        if self.task == "direction":
            from sklearn.metrics import accuracy_score, roc_auc_score
            y_bin = (y > 0).astype(int)
            self.metrics = {
                "train_accuracy": float(accuracy_score(y_bin, (y_pred > 0).astype(int))),
                "train_samples": len(y),
            }
        else:
            from sklearn.metrics import mean_absolute_error
            self.metrics = {
                "train_mae": float(mean_absolute_error(y, y_pred)),
                "train_samples": len(y),
            }

        logger.info("[%s/%s] Trained on %d samples. Metrics: %s",
                    self.regime_name, self.task, len(y), self.metrics)
        return self.metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self.is_trained or self.model is None:
            raise RuntimeError(f"[{self.regime_name}] Model not trained")
        return self.model.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> Optional[np.ndarray]:
        if not self.is_trained or self.model is None:
            return None
        if hasattr(self.model, "predict_proba"):
            return self.model.predict_proba(X)
        return None

    def feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}
        if hasattr(self.model, "feature_importances_"):
            imp = self.model.feature_importances_
            names = self.feature_names if self.feature_names else [f"f{i}" for i in range(len(imp))]
            return dict(sorted(zip(names, imp.tolist()), key=lambda x: -x[1]))
        return {}

    def save(self) -> str:
        os.makedirs(REGIME_MODELS_DIR, exist_ok=True)
        with open(self.artifact_path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "regime_name": self.regime_name,
                "task": self.task,
                "feature_names": self.feature_names,
                "metrics": self.metrics,
                "trained_at": self.trained_at,
            }, f)
        logger.info("[%s] Saved to %s", self.regime_name, self.artifact_path)
        return self.artifact_path

    def load(self) -> bool:
        if not os.path.exists(self.artifact_path):
            return False
        with open(self.artifact_path, "rb") as f:
            state = pickle.load(f)
        self.model = state["model"]
        self.feature_names = state.get("feature_names", [])
        self.metrics = state.get("metrics", {})
        self.trained_at = state.get("trained_at")
        self.is_trained = True
        logger.info("[%s] Loaded from %s", self.regime_name, self.artifact_path)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime_name": self.regime_name,
            "task": self.task,
            "is_trained": self.is_trained,
            "feature_count": len(self.feature_names),
            "metrics": self.metrics,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "artifact_path": self.artifact_path,
            "top_features": dict(list(self.feature_importance().items())[:10]),
        }

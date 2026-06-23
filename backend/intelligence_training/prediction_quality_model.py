"""
Prediction Quality Model — Phase 8.5F
Learns to predict when AQRTI's predictions will be wrong.
Output: probability of failure for any given prediction context.
"""

from __future__ import annotations

import os
import pickle
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("prediction_quality_model")

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ml_models", "meta", "prediction_quality_model.pkl",
)

QUALITY_FEATURES = [
    "confidence", "model_agreement", "historical_accuracy",
    "regime_confidence", "signal_strength", "feature_completeness",
]


class PredictionQualityModel:
    """
    Binary classifier: will this prediction succeed or fail?
    Trained on historical (confidence_features, outcome) pairs.
    """

    def __init__(self):
        self.model = None
        self.is_trained = False
        self.feature_names: List[str] = QUALITY_FEATURES
        self.metrics: Dict[str, float] = {}

    def _build_model(self):
        try:
            from lightgbm import LGBMClassifier
            return LGBMClassifier(
                n_estimators=200, learning_rate=0.05, max_depth=4,
                num_leaves=15, min_child_samples=10,
                class_weight="balanced", random_state=42, verbose=-1,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(n_estimators=150, random_state=42)

    def build_training_data(self, days_back: int = 365, db=None) -> pd.DataFrame:
        own_session = db is None
        if own_session:
            db = get_session_factory()()
        try:
            cutoff = date.today() - timedelta(days=days_back)
            rows = db.execute(text("""
                SELECT p.success, ch.confidence_score as confidence,
                       ch.model_agreement, ch.historical_accuracy,
                       ch.regime_confidence, ch.signal_strength, ch.feature_completeness
                FROM predictions p
                JOIN confidence_history ch ON ch.symbol = p.symbol AND ch.prediction_date = p.date
                WHERE p.date >= :cutoff AND p.success IS NOT NULL
                """),
                {"cutoff": cutoff},
            ).fetchall()
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame([dict(r._mapping) for r in rows])
            df["label"] = df["success"].fillna(False).astype(int)
            return df
        finally:
            if own_session:
                db.close()

    def train(self, days_back: int = 365) -> Dict[str, float]:
        df = self.build_training_data(days_back)
        if df.empty or len(df) < 30:
            logger.warning("Insufficient data to train PredictionQualityModel")
            return {}

        available_features = [f for f in self.feature_names if f in df.columns]
        X = df[available_features].fillna(0)
        y = df["label"]

        self.model = self._build_model()
        self.model.fit(X, y)
        self.feature_names = available_features
        self.is_trained = True

        from sklearn.metrics import accuracy_score, roc_auc_score
        y_pred = self.model.predict(X)
        self.metrics = {
            "train_accuracy": float(accuracy_score(y, y_pred)),
            "train_samples": len(y),
        }
        try:
            proba = self.model.predict_proba(X)[:, 1]
            self.metrics["train_auc"] = float(roc_auc_score(y, proba))
        except Exception:
            pass

        self.save()
        logger.info("PredictionQualityModel trained: %s", self.metrics)
        return self.metrics

    def predict_failure_probability(self, features: Dict[str, float]) -> float:
        """Returns probability [0,1] that the prediction will fail."""
        if not self.is_trained or self.model is None:
            return 0.5
        x = np.array([[features.get(f, 0.0) for f in self.feature_names]])
        df_x = pd.DataFrame(x, columns=self.feature_names)
        proba = self.model.predict_proba(df_x)
        # class 0 = failure (success=0), so P(failure) = proba[:,0]
        # class 1 = success, so P(failure) = 1 - proba[:,1]
        return float(1 - proba[0, 1]) if proba.shape[1] > 1 else 0.5

    def save(self):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
                "metrics": self.metrics,
            }, f)

    def load(self) -> bool:
        if not os.path.exists(MODEL_PATH):
            return False
        with open(MODEL_PATH, "rb") as f:
            state = pickle.load(f)
        self.model = state["model"]
        self.feature_names = state.get("feature_names", QUALITY_FEATURES)
        self.metrics = state.get("metrics", {})
        self.is_trained = True
        return True


_quality_model: Optional[PredictionQualityModel] = None


def get_prediction_quality_model() -> PredictionQualityModel:
    global _quality_model
    if _quality_model is None:
        _quality_model = PredictionQualityModel()
        _quality_model.load()
    return _quality_model

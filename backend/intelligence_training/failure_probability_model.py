"""
Failure Probability Model — Phase 8.5F
Learns which conditions create failures and returns a failure risk score (0-100).
"""

from __future__ import annotations

import os
import pickle
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("failure_probability_model")

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ml_models", "meta", "failure_probability_model.pkl",
)

FAILURE_FEATURES = [
    "confidence", "model_agreement", "historical_accuracy",
    "regime_confidence", "signal_strength", "feature_completeness",
    "regime_encoded",
]

REGIME_ENCODING = {
    "BULL": 1, "BEAR": -1, "SIDEWAYS": 0, "VOLATILE": -2,
}


class FailureProbabilityModel:
    """
    Predicts failure probability (0-100) for any AQRTI prediction.
    Higher score = higher chance of failure.
    """

    def __init__(self):
        self.model = None
        self.is_trained = False
        self.feature_names: List[str] = []
        self.metrics: Dict[str, float] = {}
        self.failure_conditions: List[Dict[str, Any]] = []

    def _build_model(self):
        try:
            from lightgbm import LGBMClassifier
            return LGBMClassifier(
                n_estimators=250, learning_rate=0.03, max_depth=5,
                num_leaves=20, min_child_samples=10,
                class_weight="balanced", random_state=42, verbose=-1,
            )
        except ImportError:
            from sklearn.ensemble import RandomForestClassifier
            return RandomForestClassifier(n_estimators=150, random_state=42)

    def build_training_data(self, days_back: int = 365) -> pd.DataFrame:
        db = get_session_factory()()
        try:
            cutoff = date.today() - timedelta(days=days_back)
            rows = db.execute(
                """
                SELECT p.success, p.regime, ch.confidence_score as confidence,
                       ch.model_agreement, ch.historical_accuracy,
                       ch.regime_confidence, ch.signal_strength, ch.feature_completeness
                FROM predictions p
                JOIN confidence_history ch ON ch.symbol = p.symbol AND ch.prediction_date = p.date
                WHERE p.date >= :cutoff AND p.success IS NOT NULL
                """,
                {"cutoff": cutoff},
            ).fetchall()
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame([dict(r._mapping) for r in rows])
            df["failure"] = (~df["success"].fillna(False).astype(bool)).astype(int)
            df["regime_encoded"] = df["regime"].map(REGIME_ENCODING).fillna(0)
            return df
        finally:
            db.close()

    def train(self, days_back: int = 365) -> Dict[str, float]:
        df = self.build_training_data(days_back)
        if df.empty or len(df) < 30:
            logger.warning("Insufficient data for FailureProbabilityModel")
            return {}

        feat_cols = [f for f in FAILURE_FEATURES if f in df.columns]
        X = df[feat_cols].fillna(0)
        y = df["failure"]

        self.model = self._build_model()
        self.model.fit(X, y)
        self.feature_names = feat_cols
        self.is_trained = True

        from sklearn.metrics import accuracy_score
        y_pred = self.model.predict(X)
        self.metrics = {
            "train_accuracy": float(accuracy_score(y, y_pred)),
            "failure_rate": float(y.mean()),
            "train_samples": len(y),
        }

        # Extract top failure conditions from feature importance
        if hasattr(self.model, "feature_importances_"):
            imp = self.model.feature_importances_
            top = sorted(zip(feat_cols, imp.tolist()), key=lambda x: -x[1])[:5]
            self.failure_conditions = [{"feature": f, "importance": v} for f, v in top]

        self.save()
        logger.info("FailureProbabilityModel trained: %s", self.metrics)
        return self.metrics

    def predict_failure_risk(self, features: Dict[str, float], regime: str = "BULL") -> Dict[str, Any]:
        """Return failure risk score (0-100) and breakdown."""
        if not self.is_trained or self.model is None:
            return {"failure_risk": 50.0, "status": "not_trained"}

        features_copy = dict(features)
        features_copy["regime_encoded"] = REGIME_ENCODING.get(regime, 0)
        x = np.array([[features_copy.get(f, 0.0) for f in self.feature_names]])
        df_x = pd.DataFrame(x, columns=self.feature_names)

        proba = self.model.predict_proba(df_x)
        failure_prob = float(proba[0, 1]) if proba.shape[1] > 1 else 0.5
        failure_risk = failure_prob * 100

        return {
            "failure_risk": round(failure_risk, 1),
            "failure_probability": round(failure_prob, 4),
            "risk_level": "critical" if failure_risk > 70 else (
                "high" if failure_risk > 55 else (
                    "medium" if failure_risk > 35 else "low"
                )
            ),
            "top_risk_factors": self.failure_conditions[:3],
        }

    def save(self):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
                "metrics": self.metrics,
                "failure_conditions": self.failure_conditions,
            }, f)

    def load(self) -> bool:
        if not os.path.exists(MODEL_PATH):
            return False
        with open(MODEL_PATH, "rb") as f:
            state = pickle.load(f)
        self.model = state["model"]
        self.feature_names = state.get("feature_names", FAILURE_FEATURES)
        self.metrics = state.get("metrics", {})
        self.failure_conditions = state.get("failure_conditions", [])
        self.is_trained = True
        return True


_fp_model: Optional[FailureProbabilityModel] = None


def get_failure_probability_model() -> FailureProbabilityModel:
    global _fp_model
    if _fp_model is None:
        _fp_model = FailureProbabilityModel()
        _fp_model.load()
    return _fp_model

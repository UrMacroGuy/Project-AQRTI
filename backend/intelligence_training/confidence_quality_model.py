"""
Confidence Quality Model — Phase 8.5F
Learns when AQRTI's confidence scores are well-calibrated vs. overconfident.
"""

from __future__ import annotations

import os
import pickle
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("confidence_quality_model")

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ml_models", "meta", "confidence_quality_model.pkl",
)
class ConfidenceQualityModel:
    """
    Measures and corrects confidence calibration.
    Learns a mapping: stated_confidence → actual_accuracy.
    """

    def __init__(self):
        self.calibration_map: Dict[str, float] = {}
        self.regime_calibration: Dict[str, Dict[str, float]] = {}
        self.is_trained = False

    def train(self, days_back: int = 365) -> Dict[str, float]:
        db = get_session_factory()()
        try:
            cutoff = date.today() - timedelta(days=days_back)
            rows = db.execute(text("""
                SELECT p.confidence, p.success, p.regime
                FROM predictions p
                WHERE p.date >= :cutoff AND p.success IS NOT NULL AND p.confidence IS NOT NULL
                """),
                {"cutoff": cutoff},
            ).fetchall()

            if len(rows) < 30:
                logger.warning("Insufficient data for confidence calibration")
                return {}

            df = pd.DataFrame([dict(r._mapping) for r in rows])
            df["success"] = df["success"].fillna(False).astype(bool)

            # Build confidence buckets (10% intervals)
            df["conf_bucket"] = (df["confidence"] // 10 * 10).astype(int)
            bucket_stats = df.groupby("conf_bucket")["success"].agg(["mean", "count"]).reset_index()
            self.calibration_map = {
                str(int(row["conf_bucket"])): float(row["mean"])
                for _, row in bucket_stats.iterrows()
                if row["count"] >= 5
            }

            # Regime-specific calibration
            for regime in df["regime"].dropna().unique():
                rdf = df[df["regime"] == regime]
                if len(rdf) < 10:
                    continue
                r_stats = rdf.groupby("conf_bucket")["success"].mean()
                self.regime_calibration[regime] = {
                    str(int(k)): float(v) for k, v in r_stats.items()
                }

            self.is_trained = True
            self.save()
            logger.info("ConfidenceQualityModel trained: %d buckets", len(self.calibration_map))
            return {
                "calibration_buckets": len(self.calibration_map),
                "regimes_calibrated": len(self.regime_calibration),
                "training_samples": len(df),
            }
        finally:
            db.close()

    def calibrate(self, confidence: float, regime: Optional[str] = None) -> Dict[str, float]:
        """Return calibrated accuracy for a stated confidence level."""
        bucket = str(int(confidence // 10 * 10))
        global_cal = self.calibration_map.get(bucket, confidence / 100)
        regime_cal = None
        if regime and regime in self.regime_calibration:
            regime_cal = self.regime_calibration[regime].get(bucket)

        overconfidence = confidence / 100 - global_cal if global_cal is not None else 0.0
        return {
            "stated_confidence": confidence,
            "calibrated_accuracy": global_cal,
            "regime_accuracy": regime_cal,
            "overconfidence_gap": float(overconfidence),
            "is_overconfident": overconfidence > 0.10,
        }

    def save(self):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "calibration_map": self.calibration_map,
                "regime_calibration": self.regime_calibration,
            }, f)

    def load(self) -> bool:
        if not os.path.exists(MODEL_PATH):
            return False
        with open(MODEL_PATH, "rb") as f:
            state = pickle.load(f)
        self.calibration_map = state.get("calibration_map", {})
        self.regime_calibration = state.get("regime_calibration", {})
        self.is_trained = bool(self.calibration_map)
        return True


_cal_model: Optional[ConfidenceQualityModel] = None


def get_confidence_quality_model() -> ConfidenceQualityModel:
    global _cal_model
    if _cal_model is None:
        _cal_model = ConfidenceQualityModel()
        _cal_model.load()
    return _cal_model

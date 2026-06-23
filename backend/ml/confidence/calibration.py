"""
AQRTI Probability Calibration
Applies isotonic regression calibration to model probability outputs.

Raw classifier probabilities tend to be overconfident (too extreme) or
underconfident (too moderate). Calibration maps them to empirically valid
probabilities matching observed frequencies.

Usage:
  calibrator = IsotonicCalibrator()
  calibrator.fit(y_proba_train, y_true_train)
  calibrated = calibrator.transform(y_proba_raw)
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression

from aqrti.utils.logger import get_logger
from ml.models.base_model import ML_MODELS_DIR

log = get_logger("calibration")

CALIBRATOR_DIR = ML_MODELS_DIR / "calibrators"
CALIBRATOR_DIR.mkdir(parents=True, exist_ok=True)


class IsotonicCalibrator:
    """
    Per-model isotonic regression calibrator.
    Monotone non-decreasing mapping from raw probabilities to calibrated ones.
    """

    def __init__(self, model_name: str, task: str, version: int = 1):
        self.model_name  = model_name
        self.task        = task
        self.version     = version
        self._calibrator: Optional[IsotonicRegression] = None
        self._fitted     = False

    def fit(self, y_proba: np.ndarray, y_true: np.ndarray) -> "IsotonicCalibrator":
        """
        Fit calibrator on held-out validation probabilities and true labels.
        Only applicable to classification tasks.
        """
        y_proba = np.clip(np.array(y_proba, dtype=float), 1e-6, 1 - 1e-6)
        y_true  = np.array(y_true, dtype=float)

        if len(y_proba) < 20:
            log.warning("Calibrator: too few samples (%d) for %s/%s", len(y_proba), self.model_name, self.task)
            return self

        self._calibrator = IsotonicRegression(out_of_bounds="clip")
        self._calibrator.fit(y_proba, y_true)
        self._fitted = True
        log.info("Calibrator fitted for %s/%s on %d samples", self.model_name, self.task, len(y_proba))
        return self

    def transform(self, y_proba: np.ndarray) -> np.ndarray:
        """Apply calibration. Returns probabilities unchanged if not fitted."""
        if not self._fitted or self._calibrator is None:
            return np.array(y_proba, dtype=float)
        return np.clip(self._calibrator.predict(np.array(y_proba, dtype=float)), 0.0, 1.0)

    def save(self) -> Path:
        path = CALIBRATOR_DIR / f"{self.model_name}_{self.task}_v{self.version}_calibrator.pkl"
        with open(path, "wb") as f:
            pickle.dump({"calibrator": self._calibrator, "fitted": self._fitted}, f)
        return path

    @classmethod
    def load(cls, model_name: str, task: str, version: int = 1) -> "IsotonicCalibrator":
        path = CALIBRATOR_DIR / f"{model_name}_{task}_v{version}_calibrator.pkl"
        instance = cls(model_name, task, version)
        if path.exists():
            with open(path, "rb") as f:
                data = pickle.load(f)
            instance._calibrator = data["calibrator"]
            instance._fitted     = data["fitted"]
        return instance


def calibrate_probability(
    raw_prob: float,
    model_name: str,
    task: str,
    version: int = 1,
) -> float:
    """
    Apply calibration to a single probability.
    Returns raw_prob if no calibrator is available.
    """
    try:
        calibrator = IsotonicCalibrator.load(model_name, task, version)
        result = calibrator.transform(np.array([raw_prob]))[0]
        return float(np.clip(result, 0.0, 1.0))
    except Exception:
        return float(np.clip(raw_prob, 0.0, 1.0))

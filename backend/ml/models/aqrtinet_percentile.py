"""
AQRTINet — Cross-Sectional PercentileRanker

Converts raw feature values to within-date percentile ranks (0.0–1.0).
This is the core preprocessing innovation in AQRTINet:

  Instead of "RELIANCE RSI = 65" the model sees "RELIANCE RSI is at the 78th
  percentile of all stocks today."

This makes features scale-invariant across time (market conditions change,
percentile ranks don't) and captures the cross-sectional alpha that
single-stock models miss.

Design constraints:
- No data leakage: rank boundaries fitted only on training data
- At inference time: rank against training distribution (not current day's universe)
  because the current day's universe may be unavailable at prediction time
- Handles NaN: NaN values are preserved as NaN through ranking
- Handles new features: unknown features pass through unchanged (backward compat)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


class PercentileRanker:
    """
    Fits per-feature empirical CDFs from training data, then maps values to
    percentile ranks at inference time.

    Usage:
        ranker = PercentileRanker()
        ranker.fit(X_train)                    # learn distribution from training data
        X_ranked = ranker.transform(X_test)    # map test values to [0, 1] ranks
    """

    def __init__(self, n_quantiles: int = 100):
        # Number of quantile breakpoints to store per feature (100 = 1% resolution)
        self.n_quantiles = n_quantiles
        # {feature_name: sorted np.ndarray of quantile breakpoints}
        self._quantiles: dict[str, np.ndarray] = {}
        self._fitted = False

    def fit(self, X: pd.DataFrame) -> "PercentileRanker":
        """
        Learn the empirical distribution of each feature from training data.

        Args:
            X: Training feature DataFrame (rows = samples, cols = features)
        """
        self._quantiles = {}
        q_points = np.linspace(0, 100, self.n_quantiles + 1)

        for col in X.columns:
            vals = X[col].dropna().values
            if len(vals) == 0:
                continue
            self._quantiles[col] = np.percentile(vals, q_points)

        self._fitted = True
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Map each feature value to its percentile rank in the training distribution.

        Returns a DataFrame with same shape and columns as X, values in [0, 1].
        NaN values remain NaN. Unknown columns pass through unchanged.
        """
        assert self._fitted, "Call fit() before transform()"

        result = X.copy().astype(float)

        for col in X.columns:
            if col not in self._quantiles:
                # Unknown feature (added after training) — pass through raw
                continue

            breaks = self._quantiles[col]
            vals = X[col].values.astype(float)

            # np.searchsorted gives index into breaks → divide by n_quantiles for [0,1]
            ranked = np.where(
                np.isnan(vals),
                np.nan,
                np.searchsorted(breaks, vals, side="right") / len(breaks),
            )
            result[col] = ranked

        return result

    def fit_transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return self.fit(X).transform(X)

    def is_fitted(self) -> bool:
        return self._fitted

    def feature_count(self) -> int:
        return len(self._quantiles)

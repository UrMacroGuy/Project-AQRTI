"""
MarkovRegimeDetector — observable 3-state Markov chain + optional Gaussian HMM.

Observable chain (always available, no extra dependency):
  States are Bull/Bear/Sideways from the trailing 20-day NIFTY return
  (threshold +/-5%). Builds a 3x3 transition matrix from consecutive daily
  labels, solves the stationary distribution, and derives regime_bias =
  P(Bull) - P(Bear).

Hidden Markov Model (optional, degrades gracefully if hmmlearn is absent):
  Fits hmmlearn.GaussianHMM on daily NIFTY returns + realized volatility,
  selects the state count via BIC, and exposes Viterbi-decoded regime class
  + posterior confidence per day.

This module is intentionally self-contained: no dependency on
intelligence/regime_discovery.py (the existing K-Means regime engine) or any
strategies/* file. It reads price history via markov.price_reader only.
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger

log = get_logger("markov.detector")

try:
    from hmmlearn.hmm import GaussianHMM
    _HMMLEARN_AVAILABLE = True
except ImportError:
    _HMMLEARN_AVAILABLE = False

BULL, BEAR, SIDEWAYS = "BULL", "BEAR", "SIDEWAYS"
STATES = [BEAR, SIDEWAYS, BULL]   # fixed index order: 0=BEAR, 1=SIDEWAYS, 2=BULL

# Diagonal (self-transition) floor — a fitted matrix with any diagonal entry
# below this is treated as a degenerate/noisy fit (plan §11 risk mitigation).
MIN_PERSISTENCE = 0.0   # observable chain has no floor requirement itself;
                         # callers should check regime_persistence before trusting bias.


def label_regime(trailing_return_pct: float, threshold_pct: float = 5.0) -> str:
    """Bull/Bear/Sideways from a trailing N-day return, threshold in percent."""
    if trailing_return_pct is None or (isinstance(trailing_return_pct, float) and math.isnan(trailing_return_pct)):
        return SIDEWAYS
    if trailing_return_pct > threshold_pct:
        return BULL
    if trailing_return_pct < -threshold_pct:
        return BEAR
    return SIDEWAYS


def build_daily_labels(nifty_df: pd.DataFrame, window: int = 20, threshold_pct: float = 5.0) -> pd.DataFrame:
    """
    nifty_df: DataFrame[date, close] sorted ascending.
    Returns DataFrame[date, trailing_return_pct, regime_state].
    """
    if nifty_df.empty or len(nifty_df) < window + 1:
        return pd.DataFrame(columns=["date", "trailing_return_pct", "regime_state"])
    df = nifty_df.sort_values("date").reset_index(drop=True)
    df["trailing_return_pct"] = df["close"].pct_change(periods=window) * 100.0
    df["regime_state"] = df["trailing_return_pct"].apply(lambda r: label_regime(r, threshold_pct))
    return df[["date", "trailing_return_pct", "regime_state"]]


def build_transition_matrix(labels: pd.Series) -> np.ndarray:
    """3x3 transition matrix (rows=from, cols=to) in STATES order, row-normalized."""
    idx = {s: i for i, s in enumerate(STATES)}
    counts = np.zeros((3, 3), dtype=float)
    seq = [idx[s] for s in labels if s in idx]
    for a, b in zip(seq[:-1], seq[1:]):
        counts[a, b] += 1
    row_sums = counts.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        matrix = np.divide(counts, row_sums, out=np.zeros_like(counts), where=row_sums != 0)
    # Rows with zero observations fall back to uniform (no data leak, just avoids NaN)
    for i in range(3):
        if row_sums[i, 0] == 0:
            matrix[i, :] = 1.0 / 3
    return matrix


def stationary_distribution(transition_matrix: np.ndarray) -> np.ndarray:
    """Solve pi P = pi via eigenvector of P^T with eigenvalue 1; falls back to power iteration."""
    try:
        eigvals, eigvecs = np.linalg.eig(transition_matrix.T)
        idx = np.argmin(np.abs(eigvals - 1.0))
        vec = np.real(eigvecs[:, idx])
        vec = np.clip(vec, 0, None)
        total = vec.sum()
        if total > 0:
            return vec / total
    except Exception:
        pass
    # Power iteration fallback
    pi = np.ones(3) / 3
    for _ in range(1000):
        pi = pi @ transition_matrix
    return pi / pi.sum()


def regime_bias_from_matrix(transition_matrix: np.ndarray) -> float:
    """P(Bull) - P(Bear) under the stationary distribution."""
    pi = stationary_distribution(transition_matrix)
    return float(pi[STATES.index(BULL)] - pi[STATES.index(BEAR)])


def regime_persistence(transition_matrix: np.ndarray, state: str) -> float:
    """Diagonal entry for `state` — how sticky that regime is."""
    i = STATES.index(state)
    return float(transition_matrix[i, i])


class MarkovRegimeDetector:
    """
    Fits a Gaussian HMM on NIFTY daily returns + realized volatility.
    Degrades to unavailable (fit()/decode() return None) if hmmlearn isn't
    installed — callers must handle that, never assume HMM output exists.
    """

    def __init__(self, n_states: Optional[int] = None, window_days: int = 252):
        self.n_states = n_states
        self.window_days = window_days
        self.model: Optional["GaussianHMM"] = None
        self.fitted_n_states: Optional[int] = None
        self.bic_score: Optional[float] = None

    @property
    def available(self) -> bool:
        return _HMMLEARN_AVAILABLE

    def _feature_matrix(self, returns: pd.Series) -> np.ndarray:
        vol = returns.rolling(10, min_periods=5).std().bfill()
        X = np.column_stack([returns.to_numpy(), vol.to_numpy()])
        return X

    def fit(self, nifty_df: pd.DataFrame) -> bool:
        """nifty_df: DataFrame[date, close, returns]. Returns True on success."""
        if not self.available:
            log.warning("hmmlearn not installed — MarkovRegimeDetector.fit() skipped.")
            return False
        df = nifty_df.sort_values("date").tail(self.window_days).reset_index(drop=True)
        if "returns" not in df.columns or df["returns"].isna().all():
            df = df.assign(returns=df["close"].pct_change() * 100.0)
        df = df.dropna(subset=["returns"])
        if len(df) < 60:
            log.warning("Insufficient rows (%d) for HMM fit — need >= 60.", len(df))
            return False

        X = self._feature_matrix(df["returns"])
        candidates = [self.n_states] if self.n_states else [2, 3, 4]
        best_model, best_bic, best_k = None, math.inf, None
        for k in candidates:
            try:
                model = GaussianHMM(n_components=k, covariance_type="diag",
                                     n_iter=1000, random_state=42)
                model.fit(X)
                log_likelihood = model.score(X)
                n_params = k * k + 2 * k * X.shape[1] + k  # transmat + means/covars + startprob (approx)
                bic = -2 * log_likelihood + n_params * math.log(len(X))
                if bic < best_bic:
                    best_model, best_bic, best_k = model, bic, k
            except Exception:
                log.exception("HMM fit failed for k=%d", k)
                continue

        if best_model is None:
            return False

        # Degenerate-fit guard (plan §11): reject if any state's self-transition
        # probability rounds to 1.0 (all mass collapsed into one regime).
        transmat = best_model.transmat_
        if np.any(np.diag(transmat) > 0.999):
            log.warning("Rejected degenerate HMM fit (k=%d): a state has transition prob ~1.0", best_k)
            return False

        self.model = best_model
        self.fitted_n_states = best_k
        self.bic_score = best_bic
        return True

    def decode(self, nifty_df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Viterbi-decode the fitted model over nifty_df. Returns DataFrame[date, regime_class, confidence_pct]."""
        if self.model is None:
            return None
        df = nifty_df.sort_values("date").reset_index(drop=True)
        if "returns" not in df.columns or df["returns"].isna().all():
            df = df.assign(returns=df["close"].pct_change() * 100.0)
        df = df.dropna(subset=["returns"]).reset_index(drop=True)
        if df.empty:
            return None
        X = self._feature_matrix(df["returns"])
        try:
            regime_class = self.model.predict(X)
            posteriors = self.model.predict_proba(X)
        except Exception:
            log.exception("HMM decode failed")
            return None
        confidence_pct = posteriors.max(axis=1) * 100.0
        return pd.DataFrame({
            "date": df["date"],
            "regime_class": regime_class,
            "confidence_pct": confidence_pct,
        })

    def to_json_artifact(self) -> Optional[dict]:
        """Serialize fitted model params for persistence in markov_hmm_models."""
        if self.model is None:
            return None
        return {
            "means_json":     json.dumps(self.model.means_.tolist()),
            "covars_json":    json.dumps(np.asarray(self.model.covars_).tolist()),
            "transmat_json":  json.dumps(self.model.transmat_.tolist()),
            "startprob_json": json.dumps(self.model.startprob_.tolist()),
            "n_states":       self.fitted_n_states,
            "bic_score":      self.bic_score,
        }

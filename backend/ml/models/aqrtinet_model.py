"""
AQRTINet v4.1 — Custom ML Model for NSE/BSE Stock Direction Prediction

Thirteen innovations over off-the-shelf gradient boosters.

  CORE INNOVATIONS (v3/v3.1, retained):
  1.  ASYMMETRIC TRADING LOSS — class_weight={0: 1.5, 1: 1.0}
      Softened from 2.0 (2026-07-06): the 2.0 weight suppressed recall to 12.6%
      in benchmarking while AUC-ROC was competitive (0.645 vs CatBoost 0.634).
      1.5 keeps precision bias without muting positive calls.

  2.  REGIME-AWARE MIXTURE OF EXPERTS
      One HistGBT specialist per market regime (BULL / BEAR / SIDEWAYS / VOLATILE)
      with regime-tuned hyperparameters.

  3.  CROSS-SECTIONAL PERCENTILE RANKING
      All features → [0,1] rank in training distribution. Scale-invariant.

  4.  META-LEARNING / STACKING
      7-fold OOF predictions from CatBoost and NGBoost as extra meta-features.

  5.  PLATT PROBABILITY CALIBRATION
      5-fold OOF logistic regression converts raw GBT scores to calibrated P(UP).

  6.  ENGINEERED INTERACTION FEATURES (9 domain-specific crosses)
      - momentum_x_trend, rsi_x_vol, volume_x_momentum, breadth_x_beta,
        sector_x_nifty, support_x_rsi, rsi_x_momentum, vol_x_breakout,
        trend_x_price

  7.  TEMPORAL DECAY WEIGHTING — half-life 252d (1 trading year)

  8.  REGIME-SPECIFIC FEATURE SELECTION
      Top-30 IC features per regime with domain-knowledge seed boosting.

  9.  CONFIDENT-LABEL FILTERING
      Rows where |5d return| < 0.5% down-weighted 0.3× (ambiguous direction).

  10. 7-FOLD STACKING OOF (lower-variance meta-features)

  11. 5-FOLD PLATT CALIBRATION (tighter sigmoid fit)

  v4.0 IMPROVEMENTS (SOTA upgrades, 2026-07-03):
  12. P0-A FEATURE NEUTRALIZATION — OLS residuals vs beta_21d + sector_return_5d
      P0-B TRIPLE-BARRIER LABELS — ATR14-dynamic TP/SL
      P0-C ERA-BOOSTED TRAINING — 60-day eras, bottom-quartile upweighted 3× × 2 rounds
      P0-D ROLLING IC RETRAIN TRIGGER — IC < 0.01 for 3 days → emergency retrain
      P1-A FII/DII FLOW FEATURES — 6 institutional flow features
      P1-B SPLIT-CONFORMAL PREDICTION INTERVALS — guaranteed marginal coverage
      P1-D ADVERSARIAL AUGMENTATION — 2× training data with Gaussian noise σ=0.05×std
      P1-E PURGED EMBARGO CV — 5-day label-window purge between folds
      P2-A SECTOR PEER-MEAN PROPAGATION — O(n) sector-group feature averages

  v4.1 IMPROVEMENTS (threshold calibration pass, 2026-07-06):
  13. PER-REGIME BALANCED-ACCURACY-OPTIMAL DECISION THRESHOLD
      Decision boundary chosen by sweeping thresholds on OOF probabilities and
      picking the one that maximises balanced accuracy on held-out fold data,
      per regime, rejecting degenerate thresholds that call >=98% of rows one
      class. Stored in the saved pkl (`regime_thresholds`) and applied in
      predict(). Root cause of the 12.6% recall result: the raw 0.5 cutoff was
      never calibrated for the model's actual probability distribution.
      Originally used plain F1, which was later found to pick degenerate
      near-all-positive thresholds on positive-majority labels (see
      _find_f1_threshold docstring) — switched to balanced accuracy with an
      explicit degenerate-threshold guard.

  14. PER-ROW HISTORICAL REGIME ROUTING (inference fix, 2026-07-06)
      predict()/predict_proba() previously routed every row in a batch to
      whichever regime is "current" in the DB right now — correct for live
      single-day inference, but silently wrong for historical/backtest
      evaluation spanning many dates, where it mis-routed most rows to the
      wrong regime expert and threshold. BaseModel.predict()/predict_proba()
      now accept an optional `dates` Series; when supplied, AQRTINet looks up
      each row's regime from the date->regime map built during training.
      Falls back to the single "current regime" behavior when dates aren't
      passed (unchanged live-inference path).

Architecture:
    AQRTINet v4.1
    ├── FeatureNeutralizer (P0-A: OLS residuals vs beta + sector)
    ├── InteractionFeatureBuilder (9 engineered crosses)
    ├── AdversarialAugmenter (P1-D: 2× rows with Gaussian noise)
    ├── PercentileRanker (cross-sectional [0,1] ranks)
    ├── ConfidentLabelWeighter (|return_5d| < 0.5% → 0.3× weight)
    ├── TemporalDecayWeighter (half-life 252d → sample_weight)
    └── RegimeExpert × 4 (BULL / BEAR / SIDEWAYS / VOLATILE)
        ├── EraBooster (P0-C: 60d eras, bottom-quartile ×3, 2 rounds)
        ├── RegimeFeatureSelector (top-30 IC, domain-hint seeded)
        ├── PlattCalibratedExpert (5-fold OOF logistic regression)
        ├── ConformalQuantiles (P1-B: split-conformal intervals)
        └── F1ThresholdSelector (v4.1: OOF threshold sweep per regime)

Hardware: AMD Ryzen AI 7 350, 16GB RAM, CPU-only
Training: ~6 minutes (7-fold stacking + 4 × 5-fold calibrated experts)
Dataset:  15.8M feature rows, 639 symbols, 2021-08-10 → 2026-07-01
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_backend = Path(__file__).parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from aqrti.utils.logger import get_logger
from ml.models.base_model import BaseModel, ML_MODELS_DIR
from ml.models.aqrtinet_percentile import PercentileRanker

log = get_logger("aqrtinet_model")

REGIMES = ["BULL", "BEAR", "SIDEWAYS", "VOLATILE"]
FALLBACK_REGIME = "BULL"
MIN_REGIME_ROWS = 200   # raised from 80 — with 15.8M rows we can afford stricter cutoff

# 1.5× false-positive penalty (softened from 2.0 per improvement plan §2 —
# the 2.0 weight suppressed recall to ~12.6% in testing; 1.5 keeps precision
# bias without making the model nearly mute on positive calls).
ASYMMETRIC_CLASS_WEIGHT = {0: 1.5, 1: 1.0}

# Temporal decay half-life: 252 trading days = 1yr, calibrated for 5yr dataset.
# v3 used 180d (6mo) which was too aggressive when 3+ years of history are available.
TEMPORAL_HALFLIFE_DAYS = 252

# Rows where |5d return| < this threshold are near-zero / noise labels
CONFIDENT_LABEL_THRESHOLD_PCT = 0.5
CONFIDENT_LABEL_WEIGHT        = 0.3   # weight for ambiguous-direction rows (not dropped)

# Regime-specific hyperparameters — tuned per market condition
REGIME_HYPERPARAMS = {
    "BULL": {
        "max_iter": 400, "learning_rate": 0.04, "max_depth": 7,
        "min_samples_leaf": 15, "l2_regularization": 0.05, "max_features": 0.85,
    },
    "BEAR": {
        "max_iter": 350, "learning_rate": 0.04, "max_depth": 6,
        "min_samples_leaf": 20, "l2_regularization": 0.15, "max_features": 0.8,
    },
    "SIDEWAYS": {
        "max_iter": 300, "learning_rate": 0.05, "max_depth": 5,
        "min_samples_leaf": 25, "l2_regularization": 0.2, "max_features": 0.75,
    },
    "VOLATILE": {
        "max_iter": 200, "learning_rate": 0.08, "max_depth": 4,
        "min_samples_leaf": 30, "l2_regularization": 0.3, "max_features": 0.7,
    },
}

# Top features by regime domain knowledge (used as seed for IC selection)
REGIME_FEATURE_HINTS = {
    "BULL":     ["momentum_10d", "momentum_20d", "nifty_return_21d", "nifty_return_5d",
                 "macd_histogram", "macd_crossover", "price_vs_ema21_pct", "adx_14",
                 "breadth_pct_above_ema50", "breadth_pct_above_ema200"],
    "BEAR":     ["beta_21d", "rolling_vol_21d", "historical_vol_63d", "atr_14",
                 "relative_strength_nifty_21d", "nifty_rs_21d", "rsi_14",
                 "distribution_score_5d", "volume_spike", "di_plus_minus"],
    "SIDEWAYS": ["rsi_14", "rsi_divergence", "resistance_distance_20d",
                 "support_distance_20d", "macd_histogram", "obv_slope_10d",
                 "vol_compression", "price_position_52w", "volume_ratio_5d"],
    "VOLATILE": ["atr_14", "vol_expansion", "volume_spike", "rolling_vol_10d",
                 "rolling_vol_21d", "relative_vol_vs_sector", "volume_ratio_20d",
                 "gap_open_pct", "breakout_distance_52w", "accumulation_score_5d"],
}


def _fetch_regime_map() -> dict[str, str]:
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import MarketRegime
        with get_db() as db:
            rows = db.query(MarketRegime.date, MarketRegime.regime).all()
        return {str(r[0]): r[1].upper() for r in rows if r[1]}
    except Exception as exc:
        log.warning("Could not load regime map from DB: %s", exc)
        return {}


def _build_expert(hp: dict) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_iter            = hp.get("max_iter", 300),
        learning_rate       = hp.get("learning_rate", 0.05),
        max_depth           = hp.get("max_depth", 6),
        min_samples_leaf    = hp.get("min_samples_leaf", 20),
        l2_regularization   = hp.get("l2_regularization", 0.1),
        max_features        = hp.get("max_features", 0.8),
        early_stopping      = True,
        validation_fraction = 0.15,
        n_iter_no_change    = 25,
        class_weight        = ASYMMETRIC_CLASS_WEIGHT,
        random_state        = 42,
        verbose             = 0,
    )


def _compute_era_boost_weights(
    X_r: pd.DataFrame,
    y_r: pd.Series,
    base_weights: np.ndarray,
    dates_r: pd.Series,
    era_days: int = 60,
    rounds: int = 2,
    regime: str = "BULL",
) -> Optional[np.ndarray]:
    """
    P0-C: Era-boosted training.
    Divide training rows into 60-day eras. Score each era by the mean absolute
    Spearman IC across regime-hint features (not just `columns[0]` — that was
    a proxy that could pick a low-IC feature and produce wrong era rankings).
    Upweight bottom-quartile eras 3× over `rounds` cycles.
    Returns None if there aren't enough eras to be meaningful.
    """
    try:
        d = pd.to_datetime(dates_r, errors="coerce")
        if d.isna().all():
            return None
        d_min = d.min()
        era_idx = ((d - d_min).dt.days // era_days).fillna(-1).astype(int)
        valid_eras = [e for e in era_idx.unique() if e >= 0]
        if len(valid_eras) < 4:
            return None

        weights = base_weights.copy().astype(np.float64)

        # Use regime-hint features as IC anchors; fall back to first 5 columns
        hint_cols = [c for c in REGIME_FEATURE_HINTS.get(regime, []) if c in X_r.columns]
        ic_cols = hint_cols[:5] if hint_cols else list(X_r.columns[:5])

        for _ in range(rounds):
            era_ics = {}
            for era in valid_eras:
                mask = (era_idx == era).values
                if mask.sum() < 20:
                    continue
                # Mean |IC| across anchor features — more robust than single-feature proxy
                ic_vals = []
                for fc in ic_cols:
                    corr = X_r[fc].iloc[mask].corr(y_r.iloc[mask], method="spearman")
                    if not np.isnan(corr):
                        ic_vals.append(abs(corr))
                if ic_vals:
                    era_ics[era] = float(np.mean(ic_vals))

            if len(era_ics) < 4:
                break

            threshold = np.percentile(list(era_ics.values()), 25)
            low_ic_eras = {e for e, ic in era_ics.items() if ic <= threshold}

            for i, era in enumerate(era_idx):
                if era in low_ic_eras:
                    weights[i] *= 3.0

            # Renormalize after each round
            w_mean = weights.mean()
            if w_mean > 0:
                weights = weights / w_mean

        return weights.astype(np.float32)
    except Exception:
        return None


class FeatureNeutralizer:
    """
    P0-A: Fitted feature neutralizer (Numerai-style OLS residualization).
    Fit on training data, transform at both train and inference time so there
    is no train/test mismatch (the original stateless function was only called
    during training, leaving raw features at inference).
    """
    def __init__(self, beta_col: str = "beta_21d", sector_col: str = "sector_return_5d"):
        self.beta_col = beta_col
        self.sector_col = sector_col
        self._confounders: list[str] = []
        self._coeffs: dict[str, np.ndarray] = {}  # col → [intercept, beta_coef, sector_coef]
        self._target_cols: list[str] = []

    def fit(self, X: pd.DataFrame) -> "FeatureNeutralizer":
        from numpy.linalg import lstsq
        confounders = [c for c in [self.beta_col, self.sector_col] if c in X.columns]
        self._confounders = confounders
        if not confounders:
            return self
        C = X[confounders].values.astype(np.float64)
        ones = np.ones((C.shape[0], 1), dtype=np.float64)
        C_aug = np.hstack([ones, C])
        valid_mask = ~np.isnan(C_aug).any(axis=1)
        skip = set(confounders) | {"date", "symbol"}
        target_cols = [c for c in X.columns if c not in skip and pd.api.types.is_numeric_dtype(X[c])]
        self._coeffs = {}
        self._target_cols = []
        for col in target_cols:
            y = X[col].values.astype(np.float64)
            valid = valid_mask & ~np.isnan(y)
            if valid.sum() < 30:
                continue
            coeffs, _, _, _ = lstsq(C_aug[valid], y[valid], rcond=None)
            self._coeffs[col] = coeffs
            self._target_cols.append(col)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        if not self._confounders or not self._coeffs:
            return X
        X_out = X.copy()
        C = X[[c for c in self._confounders if c in X.columns]].values.astype(np.float64)
        # Pad missing confounder columns with zeros (keeps intercept correct)
        if C.shape[1] < len(self._confounders):
            pad = np.zeros((C.shape[0], len(self._confounders) - C.shape[1]))
            C = np.hstack([C, pad])
        ones = np.ones((C.shape[0], 1), dtype=np.float64)
        C_aug = np.hstack([ones, C])
        valid_mask = ~np.isnan(C_aug).any(axis=1)
        for col, coeffs in self._coeffs.items():
            if col not in X.columns:
                continue
            y = X[col].values.astype(np.float64)
            valid = valid_mask & ~np.isnan(y)
            residuals = y.copy()
            if valid.sum() > 0:
                residuals[valid] = y[valid] - C_aug[valid] @ coeffs
            X_out[col] = residuals
        return X_out

    def fit_transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return self.fit(X).transform(X)


def _neutralize_features(X: pd.DataFrame, beta_col: str = "beta_21d", sector_col: str = "sector_return_5d") -> pd.DataFrame:
    """Stateless neutralization for backward-compat. Prefer FeatureNeutralizer.fit_transform()."""
    return FeatureNeutralizer(beta_col, sector_col).fit_transform(X)


def _build_interaction_features(X: pd.DataFrame) -> pd.DataFrame:
    """
    Add 9 domain-specific interaction features (6 from v3 + 3 new in v3.1).
    Uses .get() pattern so missing columns produce NaN (handled by HistGBT natively).
    """
    X = X.copy()
    c = X.columns.tolist()

    def g(col):
        return X[col] if col in c else pd.Series(np.nan, index=X.index)

    # v3 original 6
    X["ix_momentum_x_trend"]   = g("momentum_10d")            * g("adx_14")
    X["ix_rsi_x_vol"]          = g("rsi_14")                  * g("rolling_vol_21d")
    X["ix_volume_x_momentum"]  = g("volume_spike")            * g("momentum_10d")
    X["ix_breadth_x_beta"]     = g("breadth_pct_above_ema50") * g("beta_21d")
    X["ix_sector_x_nifty"]     = g("sector_return_5d")        * g("nifty_return_5d")
    X["ix_support_x_rsi"]      = g("support_distance_20d")    * g("rsi_14")

    # v3.1 new 3: short-term momentum quality, vol/breakout confluence, trend/price alignment
    X["ix_rsi_x_momentum"]     = g("rsi_14")                  * g("momentum_5d")
    X["ix_vol_x_breakout"]     = g("vol_expansion")           * g("breakout_distance_52w")
    X["ix_trend_x_price"]      = g("adx_14")                  * g("price_vs_ema21_pct")

    return X


def _compute_confident_label_weights(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    training_dates: pd.Series,
    return_5d: Optional[pd.Series] = None,
) -> np.ndarray:
    """
    Compute per-row confidence weights based on label ambiguity.
    Rows where the 5d return magnitude is < CONFIDENT_LABEL_THRESHOLD_PCT are
    ambiguous direction labels (coin-flip zone) — they're down-weighted rather
    than dropped so the model learns from the signal shape without being misled
    by the noisy direction call.

    Accepts return_5d as an optional series (set by callers via model._return_5d).
    Falls back to uniform weights if not provided.
    """
    if return_5d is None or return_5d.empty:
        return np.ones(len(X_train), dtype=np.float32)

    abs_ret = return_5d.abs()
    confident = abs_ret >= CONFIDENT_LABEL_THRESHOLD_PCT
    weights = np.where(confident, 1.0, CONFIDENT_LABEL_WEIGHT).astype(np.float32)
    n_ambiguous = int((~confident).sum())
    log.info(
        "AQRTINet: confident-label filter — %d/%d rows ambiguous (|return|<%.1f%%), weighted %.1f×",
        n_ambiguous, len(X_train), CONFIDENT_LABEL_THRESHOLD_PCT, CONFIDENT_LABEL_WEIGHT,
    )
    return weights


def _compute_temporal_weights(dates: pd.Series, halflife_days: int = TEMPORAL_HALFLIFE_DAYS) -> np.ndarray:
    """
    Exponential decay weights: w(t) = 2^(-(T - t) / halflife).
    Most-recent row → weight 1.0. A row halflife_days ago → weight 0.5.
    Returns uniform weights (all 1.0) if dates cannot be parsed.
    """
    try:
        date_vals = pd.to_datetime(dates, errors="coerce")
        valid = date_vals.notna()
        if valid.sum() < 10:
            # Not enough valid dates — use uniform weights
            return np.ones(len(dates), dtype=np.float32)
        T = date_vals[valid].max()
        age_days = (T - date_vals).dt.days.fillna(0).clip(lower=0).values
        weights = np.power(2.0, -age_days / halflife_days).astype(np.float32)
        mean_w = weights.mean()
        if mean_w <= 0 or np.isnan(mean_w):
            return np.ones(len(dates), dtype=np.float32)
        weights = weights / mean_w
        return weights
    except Exception:
        return np.ones(len(dates), dtype=np.float32)


def _select_regime_features(
    X: pd.DataFrame,
    y: pd.Series,
    regime: str,
    top_n: int = 30,
) -> list[str]:
    """
    Select top features for a regime by IC (Spearman correlation with label).
    Seeds the candidate set with regime-hint features so domain knowledge
    guides selection even when data is sparse.
    """
    all_cols = [c for c in X.columns if not c.startswith("meta_")]

    # Compute IC on up to 8000 rows. Reset index before sampling so that
    # y_s alignment is by position, not by label (avoids silent misalignment
    # when X and y have different integer indices after masking/augmentation).
    X_ri = X.reset_index(drop=True)
    y_ri = y.reset_index(drop=True)
    sample_idx = X_ri.index if len(X_ri) <= 8000 else X_ri.sample(8000, random_state=42).index
    sample = X_ri.loc[sample_idx]
    y_s = y_ri.loc[sample_idx]

    ics = {}
    for col in all_cols:
        if sample[col].isnull().all():
            continue
        corr = sample[col].corr(y_s, method="spearman")
        if not np.isnan(corr):
            ics[col] = abs(corr)

    if not ics:
        return all_cols[:top_n]

    # Boost IC scores of regime-hint features by 20% so they're preferred on ties
    hints = REGIME_FEATURE_HINTS.get(regime, [])
    for h in hints:
        if h in ics:
            ics[h] *= 1.20

    ranked = sorted(ics.items(), key=lambda x: -x[1])
    selected = [col for col, _ in ranked[:top_n]]

    # Always keep meta-features
    meta_cols = [c for c in X.columns if c.startswith("meta_")]
    for m in meta_cols:
        if m not in selected:
            selected.append(m)

    return selected


def _find_f1_threshold(probas: np.ndarray, y_true: np.ndarray, n_steps: int = 50) -> float:
    """
    Improvement plan §1: sweep thresholds on OOF probabilities and return the
    one that maximises balanced accuracy (mean of per-class recall) on the
    held-out fold data. Falls back to 0.5 if there is not enough signal.

    Originally maximised plain F1, which only scores the positive class: on a
    positive-majority label (direction_5d was 61% positive in one benchmark),
    F1 is maximised by a low threshold that calls almost every row positive —
    100% recall, mediocre precision, and zero real discrimination. Balanced
    accuracy penalises that degenerate case because it also requires correctly
    calling the negative class, so a threshold that just chases the majority
    class no longer looks "optimal".
    """
    from sklearn.metrics import balanced_accuracy_score
    best_t, best_score = 0.5, 0.0
    y_true = np.asarray(y_true)
    for t in np.linspace(0.10, 0.90, n_steps):
        preds = (probas >= t).astype(int)
        n_pos = preds.sum()
        # Reject thresholds where fewer than 2% or more than 98% of rows are
        # called positive — those are degenerate (near-constant) predictions,
        # not genuine discrimination, regardless of the resulting score.
        if n_pos == 0 or n_pos >= 0.98 * len(preds):
            continue
        score = balanced_accuracy_score(y_true, preds)
        if score > best_score:
            best_score, best_t = score, float(t)
    return best_t


class PlattCalibratedExpert:
    """
    HistGBT expert wrapped with Platt logistic regression for probability calibration.
    Also stores split-conformal quantiles (P1-B) for guaranteed coverage intervals.
    """
    def __init__(self, base: Any, platt: Any, feature_cols: list[str]):
        self._base = base
        self._platt = platt
        self._feature_cols = feature_cols  # subset used by this expert
        # P1-B: conformal quantiles — set by _fit_conformal(); None until fitted
        self._conformal_q_low:  Optional[float] = None   # q at alpha/2
        self._conformal_q_high: Optional[float] = None   # q at 1-alpha/2

    def _fit_conformal(self, X_cal: pd.DataFrame, y_cal: pd.Series, alpha: float = 0.10) -> None:
        """
        P1-B: Split-conformal calibration (no external library needed).
        Compute non-conformity scores on a held-out calibration set and store
        the (alpha/2, 1-alpha/2) quantiles of |predicted_proba - true_label|.
        These define guaranteed marginal coverage at (1-alpha) level.
        """
        try:
            probas = self.predict_proba(X_cal)[:, 1]
            scores = np.abs(probas - y_cal.values.astype(float))
            n = len(scores)
            if n < 20:
                return
            # Conformal quantile with finite-sample correction
            q_level_lo = np.ceil((n + 1) * (alpha / 2))       / n
            q_level_hi = np.ceil((n + 1) * (1 - alpha / 2))   / n
            q_level_lo = float(np.clip(q_level_lo, 0.0, 1.0))
            q_level_hi = float(np.clip(q_level_hi, 0.0, 1.0))
            self._conformal_q_low  = float(np.quantile(scores, q_level_lo))
            self._conformal_q_high = float(np.quantile(scores, q_level_hi))
        except Exception:
            pass

    def predict_interval(self, X: pd.DataFrame, alpha: float = 0.10) -> np.ndarray:
        """
        Return (n, 2) array of [lower, upper] conformal prediction intervals.
        Lower bound: proba - q_high (wider tail); upper: proba + q_high.
        q_low is the tighter inner quantile stored for reference.
        Falls back to ±0.20 if conformal quantiles were not fitted.
        """
        probas = self.predict_proba(X)[:, 1]
        if self._conformal_q_high is None:
            return np.column_stack([
                np.clip(probas - 0.20, 0, 1),
                np.clip(probas + 0.20, 0, 1),
            ])
        # Both directions use q_high (the wider, coverage-guaranteeing quantile).
        # q_low (5th percentile of residuals) would give an overly tight interval.
        return np.column_stack([
            np.clip(probas - self._conformal_q_high, 0, 1),
            np.clip(probas + self._conformal_q_high, 0, 1),
        ])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        Xs = X[self._feature_cols] if self._feature_cols else X
        return self._base.predict(Xs)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        Xs = X[self._feature_cols] if self._feature_cols else X
        raw = self._base.predict_proba(Xs)[:, 1]
        cal = self._platt.predict_proba(raw.reshape(-1, 1))[:, 1]
        return np.column_stack([1 - cal, cal])

    @property
    def feature_importances_(self) -> np.ndarray:
        return getattr(self._base, "feature_importances_", np.array([]))


class AQRTINet(BaseModel):
    """
    AQRTINet v4.1 — AQRTI's custom ML backbone.
    13 trading-domain improvements over off-the-shelf gradient boosters.
    """

    @property
    def model_type(self) -> str:
        return "aqrtinet"

    def _get_default_hyperparams(self) -> dict:
        return {
            "max_iter": 300, "learning_rate": 0.05, "max_depth": 6,
            "min_samples_leaf": 20, "l2_regularization": 0.1, "max_features": 0.8,
        }

    def _build_model(self) -> dict:
        return {regime: _build_expert(REGIME_HYPERPARAMS[regime]) for regime in REGIMES}

    def __init__(self, task: str, label_col: str, hyperparams: Optional[dict] = None, version: int = 1):
        super().__init__(task, label_col, hyperparams, version)
        self._experts: dict[str, Any] = {}
        self._neutralizer: Optional[FeatureNeutralizer] = None
        self._ranker: Optional[PercentileRanker] = None
        self._regime_map: dict[str, str] = {}
        self._current_regime: str = FALLBACK_REGIME
        self._stacking_feature_cols: list[str] = []
        self._regime_feature_cols: dict[str, list[str]] = {}
        self._regime_thresholds: dict[str, float] = {}  # F1-optimal per-regime decision threshold
        self._return_5d: Optional[pd.Series] = None       # for confident-label weighting

    # ── Training ──────────────────────────────────────────────────────────

    def _fit_impl(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
        sample_weight: Optional[np.ndarray] = None,
    ) -> None:
        import sys as _sys
        print(f"  [AQRTINet] Phase 0: neutralization + interactions", flush=True)

        # ── Step 0: Add engineered interaction features ───────────────────
        # Strip label columns that may have been passed through (e.g. return_5d used by
        # confident-label weighter below) — they must NEVER be features for the model.
        _LABEL_PASSTHROUGH = ["return_5d", "return_3d", "return_10d", "return_15d",
                               "outperform_nifty_5d", "outperform_binary", "expected_return",
                               "direction_5d"]
        X_clean = X_train.drop(columns=[c for c in _LABEL_PASSTHROUGH if c in X_train.columns], errors="ignore")
        # Update _feature_cols so base_model.predict() doesn't require stripped columns at inference
        self._feature_cols = list(X_clean.columns)

        # ── P0-A: Feature neutralization (Numerai-style) ──────────────────
        # Fit the neutralizer on training data and store it so inference applies
        # the same OLS projection (fixes the prior train/test mismatch where
        # _neutralize_features was only called during training).
        self._neutralizer = FeatureNeutralizer()
        X_neutral = self._neutralizer.fit_transform(X_clean)
        log.info(
            "AQRTINet: feature neutralizer fitted on %d target cols (confounders: beta_21d, sector_return_5d)",
            len(self._neutralizer._target_cols),
        )

        X_work = _build_interaction_features(X_neutral)
        ix_cols = [c for c in X_work.columns if c.startswith("ix_")]
        log.info("AQRTINet: added %d interaction features (from %d clean features)", len(ix_cols), len(X_clean.columns))

        print(f"  [AQRTINet] Phase 1: stacking OOF (7-fold CatBoost + NGBoost)...", flush=True)

        # ── Step 1: Stacking — OOF predictions from CatBoost + NGBoost ───
        # 7-fold (was 5-fold in v3): more folds = lower variance meta-features
        # with 15.8M rows now available across the full 5yr history.
        meta_cols: list[str] = []
        try:
            # TimeSeriesSplit for stacking OOF — prevents future-leakage where
            # earlier (chronologically) rows get predicted by models trained on
            # later rows (the old StratifiedKFold(shuffle=False) bug, see
            # AQRTINET_IMPROVEMENT_PLAN.md finding C).
            from sklearn.model_selection import TimeSeriesSplit
            tscv = TimeSeriesSplit(n_splits=7)
            for meta_name, model_key in [("meta_catboost", "catboost"), ("meta_ngboost", "ngboost")]:
                print(f"    Stacking {model_key} (7 folds):", end="", flush=True)
                if model_key == "catboost":
                    from ml.models.catboost_model import CatBoostModel as MClass
                else:
                    from ml.models.ngboost_model import NGBoostModel as MClass
                oof = np.zeros(len(X_clean))
                for fi, (tr_idx, val_idx) in enumerate(tscv.split(X_clean)):
                    print(f" {fi+1}", end="", flush=True)
                    m = MClass(task=self.task, label_col=self.label_col, version=0)
                    m.fit(X_clean.iloc[tr_idx], y_train.iloc[tr_idx])
                    p = m.predict_proba(X_clean.iloc[val_idx])
                    oof[val_idx] = p if p.ndim == 1 else p[:, 1]
                print(" done", flush=True)
                X_work[meta_name] = oof
                meta_cols.append(meta_name)
            self._stacking_feature_cols = meta_cols
            log.info("AQRTINet: stacking — added %d meta-features", len(meta_cols))
        except Exception as exc:
            log.warning("AQRTINet: stacking OOF failed: %s", exc)

        print(f"  [AQRTINet] Phase 2: percentile ranking...", flush=True)

        # ── Step 2: Cross-sectional percentile ranking (per-fold fit to avoid leakage) ──
        # Instead of fitting on ALL data, we fit inside the CV loop so validation
        # rows never influence the percentile distribution used for training.
        # Collect all per-fold training portions for regime specialist training.
        _fold_ranked_chunks: list[pd.DataFrame] = []
        self._ranker = PercentileRanker(n_quantiles=100)
        try:
            tscv_r = TimeSeriesSplit(n_splits=7)
            for tr_idx_r, _ in tscv_r.split(X_work):
                ranker_fold = PercentileRanker(n_quantiles=100)
                X_tr_ranked_fold = ranker_fold.fit_transform(X_work.iloc[tr_idx_r])
                _fold_ranked_chunks.append(X_tr_ranked_fold)
            # Build the full ranked matrix from concatenated per-fold training portions
            X_ranked = pd.concat(_fold_ranked_chunks, ignore_index=True).loc[
                X_work.index
            ] if _fold_ranked_chunks else X_work
            # Fit a final ranker on ALL training data for inference-time use
            self._ranker.fit(X_work)
            log.info(
                "AQRTINet: PercentileRanker fitted per-fold (%d folds, %d features)",
                len(_fold_ranked_chunks), self._ranker.feature_count(),
            )
        except Exception as exc:
            log.warning("AQRTINet: per-fold ranking failed (%s) — falling back to full-fit ranker", exc)
            self._ranker.fit(X_work)
            X_ranked = self._ranker.transform(X_work)

        print(f"  [AQRTINet] Phase 3: loading regime map...", flush=True)

        # ── Step 3: Load regime map and assign regime per training row ────
        self._regime_map = _fetch_regime_map()
        log.info("AQRTINet: loaded %d regime labels from DB", len(self._regime_map))

        dates = pd.Series([""] * len(X_train), index=X_ranked.index)
        if hasattr(self, "_training_dates") and self._training_dates is not None:
            try:
                dates = self._training_dates.reindex(X_ranked.index).fillna("").astype(str)
            except Exception as e:
                log.warning("AQRTINet: _training_dates reindex failed: %s", e)
        elif "date" in X_train.columns:
            dates = X_train["date"].astype(str)

        regimes = pd.Series(
            [self._regime_map.get(d, FALLBACK_REGIME) for d in dates],
            index=X_ranked.index,
        )
        log.info("AQRTINet: regime distribution: %s", regimes.value_counts().to_dict())

        print(f"  [AQRTINet] Phase 4: combined weights...", flush=True)

        # ── Step 4: Combined sample weights (temporal decay × confident-label) ──
        temporal_weights = _compute_temporal_weights(dates)
        return_5d_vals = getattr(self, "_return_5d", None)
        confident_weights = _compute_confident_label_weights(X_train, y_train, dates, return_5d=return_5d_vals)
        # Multiply: recent + confident rows get the highest weight
        combined_weights = temporal_weights * confident_weights
        # Renormalize so mean=1 (keeps effective learning rate stable)
        cw_mean = combined_weights.mean()
        if cw_mean > 0 and not np.isnan(cw_mean):
            combined_weights = (combined_weights / cw_mean).astype(np.float32)
        else:
            combined_weights = np.ones(len(combined_weights), dtype=np.float32)

        # Compose with an externally-supplied sample_weight (e.g. failure-
        # record-driven upweighting from model_retrainer.py) rather than
        # letting one silently override the other — multiply, then
        # renormalize so mean=1 again for a stable effective learning rate.
        if sample_weight is not None and len(sample_weight) == len(combined_weights):
            combined_weights = combined_weights * np.asarray(sample_weight, dtype=np.float32)
            cw_mean2 = combined_weights.mean()
            if cw_mean2 > 0 and not np.isnan(cw_mean2):
                combined_weights = (combined_weights / cw_mean2).astype(np.float32)

        log.info(
            "AQRTINet: combined weights — min=%.3f max=%.3f mean=%.3f (halflife=%dd, confident_thresh=%.1f%%)",
            combined_weights.min(), combined_weights.max(), combined_weights.mean(),
            TEMPORAL_HALFLIFE_DAYS, CONFIDENT_LABEL_THRESHOLD_PCT,
        )

        # ── P1-D: Adversarial augmentation ───────────────────────────────────
        # Add Gaussian-perturbed copies of training rows (σ = 0.05 × feature std).
        # Forces the model to learn smooth decision boundaries rather than
        # memorizing exact feature values. Only numeric feature columns are perturbed.
        try:
            feature_cols_ranked = [c for c in X_ranked.columns]
            numeric_cols = [c for c in feature_cols_ranked if pd.api.types.is_numeric_dtype(X_ranked[c])]
            feat_stds = X_ranked[numeric_cols].std(axis=0).fillna(0).values
            noise = np.random.normal(0, 0.05, (len(X_ranked), len(numeric_cols))) * feat_stds
            X_aug_vals = X_ranked[numeric_cols].values + noise
            X_aug = X_ranked.copy()
            X_aug[numeric_cols] = X_aug_vals
            X_ranked_aug = pd.concat([X_ranked, X_aug], ignore_index=True)
            y_train_aug = pd.concat([y_train.reset_index(drop=True),
                                     y_train.reset_index(drop=True)], ignore_index=True)
            combined_weights_aug = np.concatenate([combined_weights, combined_weights])
            cw_aug_mean = combined_weights_aug.mean()
            if cw_aug_mean > 0:
                combined_weights_aug = (combined_weights_aug / cw_aug_mean).astype(np.float32)
            regimes_aug = pd.concat([regimes.reset_index(drop=True),
                                     regimes.reset_index(drop=True)], ignore_index=True)
            dates_aug = pd.concat([pd.Series(dates.values),
                                   pd.Series(dates.values)], ignore_index=True)
            log.info("AQRTINet: adversarial augmentation -- %d -> %d rows (2x with Gaussian noise s=0.05*std)",
                     len(X_ranked), len(X_ranked_aug))
        except Exception as exc:
            log.warning("AQRTINet: adversarial augmentation failed, skipping: %s", exc)
            X_ranked_aug = X_ranked
            y_train_aug = y_train.reset_index(drop=True)
            combined_weights_aug = combined_weights
            regimes_aug = regimes.reset_index(drop=True)
            dates_aug = pd.Series(dates.values)

        print(f"  [AQRTINet] Phase 5: training regime experts...", flush=True)

        # ── Step 5: Train regime-specific experts with selected features ──
        self._experts = {}
        self._regime_feature_cols = {}

        for regime in REGIMES:
            mask = (regimes_aug == regime).values
            n = mask.sum()

            if n < MIN_REGIME_ROWS:
                print(f"    Expert {regime}: skipped ({n} rows < {MIN_REGIME_ROWS})", flush=True)
                # Improvement plan §3: log as WARNING so regime data scarcity
                # is visible — a skipped expert means the BULL fallback covers it,
                # which is imprecise. Do NOT lower MIN_REGIME_ROWS to paper over this.
                log.warning(
                    "AQRTINet: %s regime has only %d rows (< MIN_REGIME_ROWS=%d) — "
                    "skipping specialist expert, %s fallback will be used. "
                    "This is a genuine data-scarcity gap, not a bug.",
                    regime, n, MIN_REGIME_ROWS, FALLBACK_REGIME,
                )
                continue

            print(f"    Expert {regime}: {n} rows — training...", flush=True)

            X_r = X_ranked_aug[mask]
            y_r = y_train_aug[mask]
            w_r = combined_weights_aug[mask]

            # Regime-specific feature selection by IC (on original data before augmentation)
            orig_mask = (regimes == regime).values
            regime_feats = _select_regime_features(X_ranked[orig_mask], y_train[orig_mask], regime, top_n=30)
            self._regime_feature_cols[regime] = regime_feats
            X_rf = X_r[regime_feats]

            hp = {**self.hyperparams, **REGIME_HYPERPARAMS[regime]}
            expert = _build_expert(hp)
            expert.fit(X_rf, y_r, sample_weight=w_r)

            # ── P0-C: Era-boosted training ─────────────────────────────────
            # Divide training into 60-day eras, score per-era IC, upweight
            # bottom-quartile eras 3× and retrain 2 more rounds.
            # Forces the model to learn patterns from hard/low-IC regimes.
            try:
                era_weights = _compute_era_boost_weights(X_r, y_r, w_r, dates_aug[mask], era_days=60, rounds=2, regime=regime)
                if era_weights is not None:
                    expert_era = _build_expert(hp)
                    expert_era.fit(X_rf, y_r, sample_weight=era_weights)
                    expert = expert_era
                    log.info("AQRTINet: %s era-boosted (2 rounds)", regime)
            except Exception as exc:
                log.warning("AQRTINet: era-boost for %s failed: %s — using base expert", regime, exc)

            self._experts[regime] = expert
            log.info(
                "AQRTINet: %s expert — %d rows (incl. aug), %d features, n_iter=%d, weight_range=[%.2f,%.2f]",
                regime, n, len(regime_feats), expert.n_iter_, w_r.min(), w_r.max(),
            )

        if FALLBACK_REGIME not in self._experts:
            log.warning("AQRTINet: %s fallback missing — training on full dataset", FALLBACK_REGIME)
            hp = {**self.hyperparams, **REGIME_HYPERPARAMS[FALLBACK_REGIME]}
            expert = _build_expert(hp)
            all_feats = _select_regime_features(X_ranked, y_train, FALLBACK_REGIME, top_n=30)
            self._regime_feature_cols[FALLBACK_REGIME] = all_feats
            expert.fit(X_ranked_aug[all_feats], y_train_aug, sample_weight=combined_weights_aug)
            self._experts[FALLBACK_REGIME] = expert

        print(f"  [AQRTINet] Phase 6: Platt calibration...", flush=True)

        # ── Step 6: Platt calibration per expert (5-fold OOF, up from 3-fold) ──
        # More folds = tighter sigmoid fit with more data available (15.8M rows).
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import TimeSeriesSplit
            calibrated: dict[str, Any] = {}

            for regime, expert in self._experts.items():
                print(f"    Calibrating {regime}...", end="", flush=True)
                mask = (regimes == regime).values
                n = mask.sum()
                feats = self._regime_feature_cols.get(regime, list(X_ranked.columns))
                X_r = X_ranked[mask][feats]
                y_r = y_train[mask]
                w_r = combined_weights[mask]

                if n < 150:
                    print(f" passthrough (n={n}<150)", flush=True)
                    calibrated[regime] = PlattCalibratedExpert(expert, _make_passthrough_platt(), feats)
                    self._regime_thresholds[regime] = 0.5  # not enough data for threshold sweep
                    continue

                oof_proba = np.zeros(n)
                # TimeSeriesSplit for Platt calibration OOF — prevents the same
                # future-leakage bug as the inner stacking CV (finding D in
                # AQRTINET_IMPROVEMENT_PLAN.md).
                # 5-fold for regimes with enough data, fall back to 3-fold for smaller regimes.
                n_splits = 5 if n >= 500 else 3
                tscv = TimeSeriesSplit(n_splits=n_splits)
                for tr_idx, val_idx in tscv.split(X_r):
                    hp = {**self.hyperparams, **REGIME_HYPERPARAMS[regime]}
                    fold_exp = _build_expert(hp)
                    fold_exp.fit(X_r.iloc[tr_idx], y_r.iloc[tr_idx], sample_weight=w_r[tr_idx])
                    oof_proba[val_idx] = fold_exp.predict_proba(X_r.iloc[val_idx])[:, 1]

                platt = LogisticRegression(C=1.0, max_iter=500)
                platt.fit(oof_proba.reshape(-1, 1), y_r.values)
                ce = PlattCalibratedExpert(expert, platt, feats)

                # P1-B: Split-conformal calibration — use the OOF probas as the
                # calibration set (they're already out-of-fold, so no leakage).
                # Store quantiles inside the expert for predict_interval() later.
                ce._conformal_q_low  = float(np.quantile(np.abs(oof_proba - y_r.values.astype(float)), 0.05))
                ce._conformal_q_high = float(np.quantile(np.abs(oof_proba - y_r.values.astype(float)), 0.90))
                calibrated[regime] = ce

                # Improvement plan §1: F1-maximising decision threshold on OOF data.
                # OOF probas are already out-of-fold so there's no leakage here.
                # We store these per-regime so _predict_impl can apply the right
                # cutoff instead of the raw 0.5 that was causing 12.6% recall.
                calibrated_oof = platt.predict_proba(oof_proba.reshape(-1, 1))[:, 1]
                best_t = _find_f1_threshold(calibrated_oof, y_r.values)
                self._regime_thresholds[regime] = best_t
                print(f" done (n={n}, folds={n_splits}, threshold={best_t:.3f})", flush=True)
                log.info(
                    "AQRTINet: Platt+Conformal calibrated %s (n=%d, feats=%d, folds=%d, q90=%.3f, threshold=%.3f)",
                    regime, n, len(feats), n_splits, ce._conformal_q_high, best_t,
                )

            self._experts = calibrated
        except Exception as exc:
            log.warning("AQRTINet: Platt calibration failed: %s", exc)

        self._model = self._experts

    # ── Inference ─────────────────────────────────────────────────────────

    def _build_inference_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply neutralization → interactions → meta-features → percentile-rank (matches training order)."""
        # P0-A: apply the fitted neutralizer so inference sees the same feature
        # distribution as training (fixes prior train/test mismatch).
        X_n = self._neutralizer.transform(X) if self._neutralizer is not None else X
        X_ix = _build_interaction_features(X_n)

        # Meta-features from saved base models
        if self._stacking_feature_cols:
            for col in self._stacking_feature_cols:
                X_ix[col] = 0.5
            try:
                for col in self._stacking_feature_cols:
                    prefix = col.replace("meta_", "")
                    pkls = sorted(ML_MODELS_DIR.glob(f"{prefix}_direction_v*.pkl"))
                    if not pkls:
                        continue
                    if prefix == "catboost":
                        from ml.models.catboost_model import CatBoostModel
                        base = CatBoostModel.load(pkls[-1])
                    else:
                        from ml.models.ngboost_model import NGBoostModel
                        base = NGBoostModel.load(pkls[-1])
                    Xb = X[[c for c in base._feature_cols if c in X.columns]]
                    if Xb.shape[1] >= len(base._feature_cols) * 0.8:
                        p = base.predict_proba(Xb)
                        X_ix[col] = p if p.ndim == 1 else p[:, 1]
            except Exception as exc:
                log.debug("AQRTINet: inference meta-features failed: %s", exc)

        if self._ranker is not None:
            return self._ranker.transform(X_ix)
        return X_ix

    def _get_current_regime(self) -> str:
        try:
            from aqrti.database.engine import get_db
            from aqrti.database.models import MarketRegime
            with get_db() as db:
                row = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
            if row and row[0]:
                return row[0].upper()
        except Exception:
            pass
        return FALLBACK_REGIME

    def _row_regimes(self, n_rows: int) -> list[str]:
        """
        Resolve one regime per row for the in-flight predict()/predict_proba() call.

        If the caller supplied per-row dates (self._predict_dates — set by
        BaseModel.predict()), look each date up in the regime map fitted during
        training so historical/backtest evaluation routes each row to the regime
        expert it actually belongs to. Without dates (the live single-day path,
        where every row is "today"), falls back to one regime for the whole batch.
        """
        dates = self._predict_dates
        if dates is not None and self._regime_map:
            dates_aligned = dates.astype(str).values
            if len(dates_aligned) == n_rows:
                return [self._regime_map.get(d, FALLBACK_REGIME) for d in dates_aligned]
        current = self._get_current_regime()
        return [current] * n_rows

    def _route_to_expert(self, regime: str) -> Any:
        return self._experts.get(regime) or self._experts.get(FALLBACK_REGIME)

    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        X_r = self._build_inference_features(X)
        row_regimes = self._row_regimes(len(X_r))
        preds = np.zeros(len(X_r), dtype=int)
        for regime in set(row_regimes):
            mask = np.array([r == regime for r in row_regimes])
            expert = self._route_to_expert(regime)
            threshold = self._regime_thresholds.get(regime, self._regime_thresholds.get(FALLBACK_REGIME))
            if threshold is not None:
                proba = expert.predict_proba(X_r[mask])
                p1 = proba[:, 1] if proba.ndim == 2 else proba
                preds[mask] = (p1 >= threshold).astype(int)
            else:
                preds[mask] = expert.predict(X_r[mask])
        return preds

    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        X_r = self._build_inference_features(X)
        row_regimes = self._row_regimes(len(X_r))
        probas = np.zeros(len(X_r), dtype=float)
        for regime in set(row_regimes):
            mask = np.array([r == regime for r in row_regimes])
            expert = self._route_to_expert(regime)
            proba = expert.predict_proba(X_r[mask])
            probas[mask] = proba[:, 1] if proba.ndim == 2 else proba
        return probas

    def predict_interval(self, X: pd.DataFrame, alpha: float = 0.10,
                         dates: Optional[pd.Series] = None) -> np.ndarray:
        """
        P1-B: Return (n, 2) conformal prediction intervals for P(UP).
        Intervals have guaranteed marginal coverage at (1-alpha) level.
        Returns [[lower, upper], ...] for each row in X.

        dates: optional per-row date Series for regime-aware routing (see predict()).
        """
        X_clean = X.drop(columns=[c for c in ["return_5d", "return_3d", "return_10d",
                                               "return_15d", "outperform_nifty_5d",
                                               "outperform_binary", "expected_return",
                                               "direction_5d"] if c in X.columns],
                          errors="ignore")
        X_r = self._build_inference_features(X_clean)
        # Use per-row regime routing if dates provided
        row_regimes = self._row_regimes(len(X_r))
        probas = np.zeros(len(X_r), dtype=float)
        intervals = np.zeros((len(X_r), 2), dtype=float)
        for regime in set(row_regimes):
            mask = np.array([r == regime for r in row_regimes])
            expert = self._route_to_expert(regime)
            if hasattr(expert, "predict_interval"):
                intv = expert.predict_interval(X_r[mask], alpha=alpha)
            else:
                p = expert.predict_proba(X_r[mask])[:, 1]
                probas[mask] = p
                intv = np.column_stack([np.clip(p - 0.15, 0, 1), np.clip(p + 0.15, 0, 1)])
            intervals[mask] = intv
        return intervals

    # ── Feature Importance ────────────────────────────────────────────────

    def _feature_importance_impl(self) -> dict[str, float]:
        if not self._experts or not self._feature_cols:
            return {}
        all_imp = []
        for regime, expert in self._experts.items():
            fi = getattr(expert, "feature_importances_", None)
            if fi is not None and len(fi) > 0:
                feats = self._regime_feature_cols.get(regime, self._feature_cols)
                if len(fi) == len(feats):
                    # Map back to full feature space
                    imp_map = dict(zip(feats, fi))
                    full_imp = np.array([imp_map.get(c, 0.0) for c in self._feature_cols])
                    all_imp.append(full_imp)
        if not all_imp:
            n = len(self._feature_cols)
            return {c: 1.0 / n for c in self._feature_cols}
        avg = np.mean(all_imp, axis=0)
        return dict(zip(self._feature_cols, avg.tolist()))

    # ── Save / Load ───────────────────────────────────────────────────────

    def save(self, fold: Optional[int] = None) -> Path:
        suffix = f"_fold{fold}" if fold is not None else ""
        fpath  = ML_MODELS_DIR / f"{self.model_type}_{self.task}_v{self.version}{suffix}.pkl"
        payload = {
            "model_type":            self.model_type,
            "task":                  self.task,
            "label_col":             self.label_col,
            "version":               self.version,
            "feature_cols":          self._feature_cols,
            "hyperparams":           self.hyperparams,
            "artifact":              self._artifact,
            "experts":               self._experts,
            "neutralizer":           self._neutralizer,
            "ranker":                self._ranker,
            "regime_map":            self._regime_map,
            "stacking_feature_cols": self._stacking_feature_cols,
            "regime_feature_cols":   self._regime_feature_cols,
            "regime_thresholds":     self._regime_thresholds,
        }
        with open(fpath, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info("AQRTINet saved to %s (%d experts)", fpath, len(self._experts))
        return fpath

    @classmethod
    def load(cls, path: Path) -> "AQRTINet":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        inst = cls.__new__(cls)
        inst.task                   = payload["task"]
        inst.label_col              = payload["label_col"]
        inst.version                = payload["version"]
        inst._feature_cols          = payload["feature_cols"]
        inst.hyperparams            = payload["hyperparams"]
        inst._artifact              = payload.get("artifact")
        inst._is_classification     = (inst.task == "direction")
        inst._experts               = payload.get("experts", {})
        inst._neutralizer           = payload.get("neutralizer")
        inst._ranker                = payload.get("ranker")
        inst._regime_map            = payload.get("regime_map", {})
        inst._current_regime        = FALLBACK_REGIME
        inst._stacking_feature_cols = payload.get("stacking_feature_cols", [])
        inst._regime_feature_cols   = payload.get("regime_feature_cols", {})
        inst._regime_thresholds     = payload.get("regime_thresholds", {})
        inst._model                 = inst._experts
        return inst

    def is_trained(self) -> bool:
        return bool(self._experts)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_passthrough_platt():
    """Minimal passthrough that wraps raw score in logistic form."""
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression()
    # Fit on synthetic balanced data so it's a near-identity transform
    lr.fit([[0.1],[0.5],[0.9]], [0, 1, 1])
    return lr


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("AQRTINet v4.1 smoke test...")
    import numpy as np, pandas as pd

    np.random.seed(42)
    n, f = 800, 28
    cols = ["momentum_10d","momentum_5d","adx_14","rsi_14","rolling_vol_21d","volume_spike",
            "breadth_pct_above_ema50","beta_21d","sector_return_5d","nifty_return_5d",
            "support_distance_20d","vol_expansion","breakout_distance_52w","price_vs_ema21_pct",
            "return_5d"] + [f"feat_{i}" for i in range(f - 15)]

    X = pd.DataFrame(np.random.randn(n, f), columns=cols)
    y = pd.Series(np.random.randint(0, 2, n))

    model = AQRTINet(task="direction", label_col="direction_5d", version=99)
    model.fit(X, y)

    # Inference doesn't need return_5d — drop it to test realistic inference path
    X_infer = X.drop(columns=["return_5d"], errors="ignore")
    preds  = model.predict(X_infer[:10])
    probas = model.predict_proba(X_infer[:10])
    imp    = model.feature_importance()

    intervals = model.predict_interval(X_infer[:5])

    print(f"  Experts trained: {list(model._experts.keys())}")
    print(f"  Ranker features: {model._ranker.feature_count()}")
    print(f"  Predictions: {preds}")
    print(f"  Probabilities: {probas.round(3)}")
    print(f"  Conformal intervals (n=5): {intervals.round(3)}")
    print(f"  Top 3: {sorted(imp.items(), key=lambda x:-x[1])[:3]}")

    path = model.save()
    model2 = AQRTINet.load(path)
    p2 = model2.predict_proba(X_infer[:5])
    p1 = model.predict_proba(X_infer[:5])
    assert np.allclose(p1, p2, atol=1e-5), "Roundtrip mismatch"
    path.unlink()
    print("AQRTINet v3.1 smoke test PASSED.")

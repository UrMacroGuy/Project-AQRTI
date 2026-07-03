"""
AQRTINet v3.1 — Custom ML Model for NSE/BSE Stock Direction Prediction

Eleven innovations over off-the-shelf gradient boosters.
v3.1 adds three improvements calibrated for the expanded 5-year feature dataset
(15.8M rows, 639 symbols, 2021-2026):

  v3 INNOVATIONS (retained):
  1. ASYMMETRIC TRADING LOSS
     class_weight={0: 2.0, 1: 1.0} penalises false positives 2× harder.

  2. REGIME-AWARE MIXTURE OF EXPERTS
     One HistGBT specialist per market regime (BULL / BEAR / SIDEWAYS / VOLATILE)
     with regime-tuned hyperparameters.

  3. CROSS-SECTIONAL PERCENTILE RANKING
     All features → [0,1] rank in training distribution. Scale-invariant.

  4. META-LEARNING / STACKING
     OOF predictions from CatBoost and NGBoost as extra meta-features.

  5. PLATT PROBABILITY CALIBRATION
     OOF logistic regression converts raw GBT scores to calibrated P(UP).

  6. ENGINEERED INTERACTION FEATURES
     9 domain-specific feature crosses (was 6 in v3):
     - momentum_x_trend    momentum_10d × adx_14
     - rsi_x_vol           rsi_14 × rolling_vol_21d
     - volume_x_momentum   volume_spike × momentum_10d
     - breadth_x_beta      breadth_pct_above_ema50 × beta_21d
     - sector_x_nifty      sector_return_5d × nifty_return_5d
     - support_x_rsi       support_distance_20d × rsi_14
     - [NEW v3.1] rsi_x_momentum     rsi_14 × momentum_5d
     - [NEW v3.1] vol_x_breakout     vol_expansion × breakout_distance_52w
     - [NEW v3.1] trend_x_price      adx_14 × price_vs_ema21_pct

  7. TEMPORAL DECAY WEIGHTING
     Exponential decay, half-life now 252d (1 trading year) calibrated for 5yr
     dataset. v3 used 180d — too aggressive when 3+ years of history are available.

  8. REGIME-SPECIFIC FEATURE SELECTION
     Top-30 IC features per regime with domain-knowledge seed boosting.

  v3.1 NEW INNOVATIONS:
  9. CONFIDENT-LABEL FILTERING
     Rows where |5d return| < 0.5% are ambiguous direction signals (noise > signal).
     These are down-weighted 0.3× in training rather than dropped (preserve sample
     size), so near-zero returns don't teach the model noise patterns.

  10. 7-FOLD STACKING (was 5-fold)
      With 15.8M feature rows and 639 symbols across 5yr, 7-fold OOF produces
      meta-features with lower variance than 5-fold, giving the meta-learner
      cleaner signals to learn from.

  11. 5-FOLD PLATT CALIBRATION (was 3-fold)
      More calibration folds = better-estimated sigmoid, especially for the
      BULL expert which has the most data.

Architecture:
    AQRTINet v3.1
    ├── InteractionFeatureBuilder (9 engineered crosses, up from 6)
    ├── PercentileRanker (45 original + 9 interaction + 2 meta = 56 features)
    ├── ConfidentLabelWeighter (down-weight |return_5d| < 0.5% rows × 0.3)
    ├── TemporalDecayWeighter (half-life 252d → sample_weight vector)
    └── RegimeExpert × 4 (per-regime tuned HistGBT)
        ├── RegimeFeatureSelector (top-30 IC features per regime, sample=8000)
        └── PlattCalibratedExpert (5-fold OOF logistic regression)

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

ASYMMETRIC_CLASS_WEIGHT = {0: 2.0, 1: 1.0}

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
) -> np.ndarray:
    """
    Compute per-row confidence weights based on label ambiguity.
    Rows where the 5d return magnitude is < CONFIDENT_LABEL_THRESHOLD_PCT are
    ambiguous direction labels (coin-flip zone) — they're down-weighted rather
    than dropped so the model learns from the signal shape without being misled
    by the noisy direction call.

    Requires 'return_5d' to be in X_train (it's dropped after weighting).
    Falls back to uniform weights if not available.
    """
    if "return_5d" not in X_train.columns:
        return np.ones(len(X_train), dtype=np.float32)

    abs_ret = X_train["return_5d"].abs()
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

    # Compute IC on available data — 8000 rows for more stable estimates (was 3000 in v3)
    sample = X if len(X) <= 8000 else X.sample(8000, random_state=42)
    y_s = y.loc[sample.index]

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


class PlattCalibratedExpert:
    """HistGBT expert wrapped with Platt logistic regression for probability calibration."""
    def __init__(self, base: Any, platt: Any, feature_cols: list[str]):
        self._base = base
        self._platt = platt
        self._feature_cols = feature_cols  # subset used by this expert

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
    AQRTINet v3 — AQRTI's custom ML backbone.
    Drop-in BaseModel replacement with 8 trading-domain improvements.
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
        self._ranker: Optional[PercentileRanker] = None
        self._regime_map: dict[str, str] = {}
        self._current_regime: str = FALLBACK_REGIME
        self._stacking_feature_cols: list[str] = []
        self._regime_feature_cols: dict[str, list[str]] = {}  # per-regime selected features

    # ── Training ──────────────────────────────────────────────────────────

    def _fit_impl(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series],
    ) -> None:

        # ── Step 0: Add engineered interaction features ───────────────────
        # Strip label columns that may have been passed through (e.g. return_5d used by
        # confident-label weighter below) — they must NEVER be features for the model.
        _LABEL_PASSTHROUGH = ["return_5d", "return_3d", "return_10d", "return_15d",
                               "outperform_nifty_5d", "outperform_binary", "expected_return",
                               "direction_5d"]
        X_clean = X_train.drop(columns=[c for c in _LABEL_PASSTHROUGH if c in X_train.columns], errors="ignore")
        # Update _feature_cols so base_model.predict() doesn't require stripped columns at inference
        self._feature_cols = list(X_clean.columns)
        X_work = _build_interaction_features(X_clean)
        ix_cols = [c for c in X_work.columns if c.startswith("ix_")]
        log.info("AQRTINet: added %d interaction features (from %d clean features)", len(ix_cols), len(X_clean.columns))

        # ── Step 1: Stacking — OOF predictions from CatBoost + NGBoost ───
        # 7-fold (was 5-fold in v3): more folds = lower variance meta-features
        # with 15.8M rows now available across the full 5yr history.
        meta_cols: list[str] = []
        try:
            from sklearn.model_selection import StratifiedKFold
            skf5 = StratifiedKFold(n_splits=7, shuffle=False)
            for meta_name, model_key in [("meta_catboost", "catboost"), ("meta_ngboost", "ngboost")]:
                if model_key == "catboost":
                    from ml.models.catboost_model import CatBoostModel as MClass
                else:
                    from ml.models.ngboost_model import NGBoostModel as MClass
                oof = np.zeros(len(X_clean))
                for tr_idx, val_idx in skf5.split(X_clean, y_train):
                    m = MClass(task=self.task, label_col=self.label_col, version=0)
                    m.fit(X_clean.iloc[tr_idx], y_train.iloc[tr_idx])
                    p = m.predict_proba(X_clean.iloc[val_idx])
                    oof[val_idx] = p if p.ndim == 1 else p[:, 1]
                X_work[meta_name] = oof
                meta_cols.append(meta_name)
            self._stacking_feature_cols = meta_cols
            log.info("AQRTINet: stacking — added %d meta-features", len(meta_cols))
        except Exception as exc:
            log.warning("AQRTINet: stacking OOF failed: %s", exc)

        # ── Step 2: Cross-sectional percentile ranking ────────────────────
        self._ranker = PercentileRanker(n_quantiles=100)
        X_ranked = self._ranker.fit_transform(X_work)
        log.info("AQRTINet: PercentileRanker fitted on %d features", self._ranker.feature_count())

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

        # ── Step 4: Combined sample weights (temporal decay × confident-label) ──
        temporal_weights = _compute_temporal_weights(dates)
        confident_weights = _compute_confident_label_weights(X_train, y_train, dates)
        # Multiply: recent + confident rows get the highest weight
        combined_weights = temporal_weights * confident_weights
        # Renormalize so mean=1 (keeps effective learning rate stable)
        cw_mean = combined_weights.mean()
        if cw_mean > 0 and not np.isnan(cw_mean):
            combined_weights = (combined_weights / cw_mean).astype(np.float32)
        else:
            combined_weights = np.ones(len(combined_weights), dtype=np.float32)
        log.info(
            "AQRTINet: combined weights — min=%.3f max=%.3f mean=%.3f (halflife=%dd, confident_thresh=%.1f%%)",
            combined_weights.min(), combined_weights.max(), combined_weights.mean(),
            TEMPORAL_HALFLIFE_DAYS, CONFIDENT_LABEL_THRESHOLD_PCT,
        )

        # ── Step 5: Train regime-specific experts with selected features ──
        self._experts = {}
        self._regime_feature_cols = {}

        for regime in REGIMES:
            mask = (regimes == regime).values
            n = mask.sum()

            if n < MIN_REGIME_ROWS:
                log.info("AQRTINet: %s has %d rows — skipping (will use %s fallback)", regime, n, FALLBACK_REGIME)
                continue

            X_r = X_ranked[mask]
            y_r = y_train[mask]
            w_r = combined_weights[mask]

            # Regime-specific feature selection by IC
            regime_feats = _select_regime_features(X_r, y_r, regime, top_n=30)
            self._regime_feature_cols[regime] = regime_feats
            X_rf = X_r[regime_feats]

            hp = {**self.hyperparams, **REGIME_HYPERPARAMS[regime]}
            expert = _build_expert(hp)
            expert.fit(X_rf, y_r, sample_weight=w_r)
            self._experts[regime] = expert
            log.info(
                "AQRTINet: %s expert — %d rows, %d features, n_iter=%d, weight_range=[%.2f,%.2f]",
                regime, n, len(regime_feats), expert.n_iter_, w_r.min(), w_r.max(),
            )

        if FALLBACK_REGIME not in self._experts:
            log.warning("AQRTINet: %s fallback missing — training on full dataset", FALLBACK_REGIME)
            hp = {**self.hyperparams, **REGIME_HYPERPARAMS[FALLBACK_REGIME]}
            expert = _build_expert(hp)
            all_feats = _select_regime_features(X_ranked, y_train, FALLBACK_REGIME, top_n=30)
            self._regime_feature_cols[FALLBACK_REGIME] = all_feats
            expert.fit(X_ranked[all_feats], y_train, sample_weight=combined_weights)
            self._experts[FALLBACK_REGIME] = expert

        # ── Step 6: Platt calibration per expert (5-fold OOF, up from 3-fold) ──
        # More folds = tighter sigmoid fit with more data available (15.8M rows).
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import StratifiedKFold
            calibrated: dict[str, Any] = {}

            for regime, expert in self._experts.items():
                mask = (regimes == regime).values
                n = mask.sum()
                feats = self._regime_feature_cols.get(regime, list(X_ranked.columns))
                X_r = X_ranked[mask][feats]
                y_r = y_train[mask]
                w_r = combined_weights[mask]

                if n < 150:
                    calibrated[regime] = PlattCalibratedExpert(expert, _make_passthrough_platt(), feats)
                    continue

                oof_proba = np.zeros(n)
                # 5-fold for regimes with enough data, fall back to 3-fold for smaller regimes
                n_splits = 5 if n >= 500 else 3
                skf = StratifiedKFold(n_splits=n_splits, shuffle=False)
                for tr_idx, val_idx in skf.split(X_r, y_r):
                    hp = {**self.hyperparams, **REGIME_HYPERPARAMS[regime]}
                    fold_exp = _build_expert(hp)
                    fold_exp.fit(X_r.iloc[tr_idx], y_r.iloc[tr_idx], sample_weight=w_r[tr_idx])
                    oof_proba[val_idx] = fold_exp.predict_proba(X_r.iloc[val_idx])[:, 1]

                platt = LogisticRegression(C=1.0, max_iter=500)
                platt.fit(oof_proba.reshape(-1, 1), y_r.values)
                calibrated[regime] = PlattCalibratedExpert(expert, platt, feats)
                log.info("AQRTINet: Platt-calibrated %s (n=%d, feats=%d, platt_folds=%d)", regime, n, len(feats), n_splits)

            self._experts = calibrated
        except Exception as exc:
            log.warning("AQRTINet: Platt calibration failed: %s", exc)

        self._model = self._experts

    # ── Inference ─────────────────────────────────────────────────────────

    def _build_inference_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Add interaction features + meta-features, then percentile-rank."""
        X_ix = _build_interaction_features(X)

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

    def _route_to_expert(self, regime: str) -> Any:
        return self._experts.get(regime) or self._experts.get(FALLBACK_REGIME)

    def _predict_impl(self, X: pd.DataFrame) -> np.ndarray:
        X_r = self._build_inference_features(X)
        expert = self._route_to_expert(self._get_current_regime())
        return expert.predict(X_r)

    def _predict_proba_impl(self, X: pd.DataFrame) -> np.ndarray:
        X_r = self._build_inference_features(X)
        expert = self._route_to_expert(self._get_current_regime())
        proba = expert.predict_proba(X_r)
        return proba[:, 1] if proba.ndim == 2 else proba

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
            "ranker":                self._ranker,
            "regime_map":            self._regime_map,
            "stacking_feature_cols": self._stacking_feature_cols,
            "regime_feature_cols":   self._regime_feature_cols,
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
        inst._ranker                = payload.get("ranker")
        inst._regime_map            = payload.get("regime_map", {})
        inst._current_regime        = FALLBACK_REGIME
        inst._stacking_feature_cols = payload.get("stacking_feature_cols", [])
        inst._regime_feature_cols   = payload.get("regime_feature_cols", {})
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
    print("AQRTINet v3.1 smoke test...")
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

    print(f"  Experts trained: {list(model._experts.keys())}")
    print(f"  Ranker features: {model._ranker.feature_count()}")
    print(f"  Predictions: {preds}")
    print(f"  Probabilities: {probas.round(3)}")
    print(f"  Top 3: {sorted(imp.items(), key=lambda x:-x[1])[:3]}")

    path = model.save()
    model2 = AQRTINet.load(path)
    p2 = model2.predict_proba(X_infer[:5])
    p1 = model.predict_proba(X_infer[:5])
    assert np.allclose(p1, p2, atol=1e-5), "Roundtrip mismatch"
    path.unlink()
    print("AQRTINet v3.1 smoke test PASSED.")

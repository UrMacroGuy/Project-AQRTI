"""
AQRTI Training Dataset
Wraps the full dataset with chronological splits and feature selection.

Walk-forward compatible: all splits are strictly time-ordered.
No test date ever appears in any training set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from aqrti.utils.logger import get_logger
from ml.datasets.dataset_builder import (
    build_full_dataset,
    get_feature_columns,
    fill_feature_nans,
)
from ml.datasets.label_generator import LABEL_COLUMNS

log = get_logger("training_dataset")

# Gap between train end and test start (trading days approximated as calendar days)
TRAIN_TEST_GAP_DAYS = 14

# Default walk-forward fold configuration — tuned for ~1 year of available history
WF_TRAIN_YEARS = 0.5     # minimum training window (6 months) — fits 1-year history
WF_TEST_MONTHS = 2       # test window per fold in months
WF_STEP_MONTHS = 2       # slide step per fold


@dataclass
class DataSplit:
    """A single chronological train/test split."""
    fold:            int
    train_start:     date
    train_end:       date
    test_start:      date
    test_end:        date
    X_train:         pd.DataFrame = field(repr=False)
    y_train:         pd.Series    = field(repr=False)
    X_test:          pd.DataFrame = field(repr=False)
    y_test:          pd.Series    = field(repr=False)
    feature_cols:    list[str]    = field(repr=False)
    scaler:          Optional[object] = field(default=None, repr=False)
    sample_weights:  Optional[pd.Series] = field(default=None, repr=False)


@dataclass
class TrainingDataset:
    """Container for the full prepared training dataset."""
    df:             pd.DataFrame
    feature_cols:   list[str]
    label_col:      str
    folds:          list[DataSplit] = field(default_factory=list)
    scaler:         Optional[RobustScaler] = field(default=None)

    @property
    def n_symbols(self) -> int:
        return self.df["symbol"].nunique()

    @property
    def n_rows(self) -> int:
        return len(self.df)

    @property
    def date_range(self) -> tuple[date, date]:
        return self.df["date"].min(), self.df["date"].max()


def select_features_by_ic(
    df: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    top_n: int = 40,
) -> list[str]:
    """
    Rank features by absolute Information Coefficient (Spearman rank correlation
    with the label). Returns top_n features.

    IC is computed per date (cross-sectional) then averaged across dates.
    This is the standard quantitative finance approach.
    """
    if len(df) < 100 or df[label_col].nunique() < 2:
        return feature_cols[:top_n]

    # Sample up to 2000 rows for speed during feature selection
    sample = df if len(df) <= 2000 else df.sample(2000, random_state=42)

    ics = {}
    for feat in feature_cols:
        if sample[feat].isnull().all():
            continue
        # Spearman correlation (rank-based, robust to outliers)
        corr = sample[feat].corr(sample[label_col], method="spearman")
        if not np.isnan(corr):
            ics[feat] = abs(corr)

    if not ics:
        return feature_cols[:top_n]

    ranked = sorted(ics.items(), key=lambda x: x[1], reverse=True)
    selected = [feat for feat, _ in ranked[:top_n]]
    log.info("Feature selection: kept %d / %d features by IC", len(selected), len(feature_cols))
    return selected


def build_walk_forward_folds(
    df: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    scale: bool = True,
    sample_weights: Optional[pd.Series] = None,
) -> list[DataSplit]:
    """
    Build all walk-forward folds with expanding training windows.

    Fold structure:
      Fold 1: train [start .. T1], gap, test [T1+gap .. T1+gap+6m]
      Fold 2: train [start .. T1+6m], gap, test [T1+6m+gap .. T1+6m+gap+6m]
      ...

    The training window expands by WF_STEP_MONTHS each fold.
    """
    df = df.sort_values("date").reset_index(drop=True)
    all_dates = sorted(df["date"].unique())

    if not all_dates:
        return []

    data_start = all_dates[0]
    data_end   = all_dates[-1]

    # Earliest possible test start: after minimum train window
    min_train_end = data_start + timedelta(days=WF_TRAIN_YEARS * 365)

    folds = []
    fold_idx = 0

    # First test window starts at min_train_end + gap
    test_start = min_train_end + timedelta(days=TRAIN_TEST_GAP_DAYS)

    while True:
        test_end = test_start + timedelta(days=WF_TEST_MONTHS * 30)
        if test_end > data_end:
            break

        train_end = test_start - timedelta(days=TRAIN_TEST_GAP_DAYS)

        train_mask = (df["date"] >= data_start) & (df["date"] <= train_end)
        test_mask  = (df["date"] >= test_start) & (df["date"] <= test_end)

        X_train = df.loc[train_mask, feature_cols].copy()
        y_train = df.loc[train_mask, label_col].copy()
        X_test  = df.loc[test_mask, feature_cols].copy()
        y_test  = df.loc[test_mask, label_col].copy()

        if len(X_train) < 200 or len(X_test) < 20:
            test_start += timedelta(days=WF_STEP_MONTHS * 30)
            continue

        scaler = None
        if scale:
            scaler = RobustScaler()
            X_train = pd.DataFrame(
                scaler.fit_transform(X_train),
                columns=feature_cols,
                index=X_train.index,
            )
            X_test = pd.DataFrame(
                scaler.transform(X_test),
                columns=feature_cols,
                index=X_test.index,
            )

        # Slice sample weights for this fold's training rows
        fold_weights = None
        if sample_weights is not None:
            fold_weights = sample_weights.loc[train_mask].reindex(X_train.index)

        folds.append(DataSplit(
            fold           = fold_idx,
            train_start    = data_start,
            train_end      = train_end,
            test_start     = test_start,
            test_end       = test_end,
            X_train        = X_train,
            y_train        = y_train,
            X_test         = X_test,
            y_test         = y_test,
            feature_cols   = feature_cols,
            scaler         = scaler,
            sample_weights = fold_weights,
        ))

        fold_idx   += 1
        test_start += timedelta(days=WF_STEP_MONTHS * 30)

    log.info("Built %d walk-forward folds", len(folds))
    return folds


def build_failure_sample_weights(df: pd.DataFrame, lookback_days: int = 90) -> pd.Series:
    """
    Query FailureRecord table and upweight training rows that match known failure
    patterns (symbol + date combinations where the model was wrong).

    Failure rows get weight 2.0 (double emphasis on learning from mistakes).
    Normal rows get weight 1.0.
    """
    weights = pd.Series(1.0, index=df.index)
    try:
        import sys, os
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from aqrti.database.engine import get_db
        from aqrti.database.models import FailureRecord
        from datetime import date, timedelta

        cutoff = date.today() - timedelta(days=lookback_days)
        with get_db() as db:
            failures = db.query(
                FailureRecord.symbol,
                FailureRecord.failure_date,
                FailureRecord.severity,
            ).filter(FailureRecord.failure_date >= cutoff).all()

        if not failures:
            return weights

        # Build lookup: (symbol, date) → severity weight
        severity_boost = {"critical": 3.0, "high": 2.5, "medium": 2.0, "low": 1.5}
        failure_map: dict[tuple, float] = {}
        for f in failures:
            key = (f.symbol, f.failure_date)
            boost = severity_boost.get(f.severity or "medium", 2.0)
            failure_map[key] = max(failure_map.get(key, 1.0), boost)

        # Apply weights where df (symbol, date) matches a failure
        df_dates = df["date"].dt.date if hasattr(df["date"], "dt") else df["date"]
        for idx, (sym, dt) in enumerate(zip(df["symbol"], df_dates)):
            key = (sym, dt)
            if key in failure_map:
                weights.iloc[idx] = failure_map[key]

        n_upweighted = (weights > 1.0).sum()
        log.info("Sample weights: %d rows upweighted from %d failure records", n_upweighted, len(failures))
    except Exception as e:
        log.debug("Could not build failure sample weights: %s", e)

    return weights


def _get_decayed_features(lookback_days: int = 30) -> set[str]:
    """
    Query FeatureDecayHistory and return feature names flagged as 'severe' or
    'moderate' in the last N days.  These are excluded from training so the
    model doesn't learn from stale predictors.
    """
    try:
        from datetime import timedelta
        from aqrti.database.engine import get_db
        from aqrti.database.models import FeatureDecayHistory
        cutoff = date.today() - timedelta(days=lookback_days)
        with get_db() as db:
            rows = db.query(FeatureDecayHistory.feature_name).filter(
                FeatureDecayHistory.measured_date >= cutoff,
                FeatureDecayHistory.decay_severity.in_(["severe", "moderate"]),
                FeatureDecayHistory.decay_flag.is_(True),
            ).all()
        decayed = {r[0] for r in rows}
        if decayed:
            log.info("Feature decay: dropping %d decayed features from training: %s",
                     len(decayed), sorted(decayed)[:10])
        return decayed
    except Exception as e:
        log.debug("Could not load decayed features: %s", e)
        return set()


def prepare_training_dataset(
    label_col: str = "direction_5d",
    top_features: int = 40,
    version: int = 1,
    scale: bool = True,
) -> TrainingDataset:
    """
    Full pipeline:
      1. Build dataset from DB (features + labels joined)
      2. Fill NaNs
      3. Select top features by IC
      4. Build walk-forward folds

    Args:
        label_col:    Which label column to target (see LABEL_COLUMNS)
        top_features: How many features to keep via IC ranking
        version:      Feature version to load from feature_store
        scale:        Whether to apply RobustScaler per fold

    Returns:
        TrainingDataset with .df, .feature_cols, .folds populated
    """
    assert label_col in LABEL_COLUMNS, f"Unknown label: {label_col}. Choose from {LABEL_COLUMNS}"

    log.info("Building full dataset (label=%s, version=%d)...", label_col, version)
    df = build_full_dataset(version=version)

    if df.empty:
        log.error("Empty dataset — no training data available")
        return TrainingDataset(df=df, feature_cols=[], label_col=label_col)

    df = fill_feature_nans(df)

    # Drop rows where the target label is null
    df = df.dropna(subset=[label_col]).reset_index(drop=True)

    raw_features = get_feature_columns(df)
    log.info("Raw features available: %d", len(raw_features))

    # Remove decayed features BEFORE IC selection so the top-N budget isn't wasted
    # on features that will be dropped anyway after selection.
    decayed = _get_decayed_features(lookback_days=30)
    if decayed:
        before = len(raw_features)
        raw_features = [f for f in raw_features if f not in decayed]
        log.info(
            "Dropped %d decayed features before IC selection (%d → %d candidates)",
            before - len(raw_features), before, len(raw_features),
        )

    # Feature selection by IC on training portion only (no leakage: use first 80% for IC)
    cutoff_idx  = int(len(df) * 0.80)
    df_for_ic   = df.iloc[:cutoff_idx]
    feature_cols = select_features_by_ic(df_for_ic, raw_features, label_col, top_n=top_features)

    # Final dataset uses only selected features + labels
    keep_cols = ["symbol", "date"] + feature_cols + LABEL_COLUMNS
    df = df[[c for c in keep_cols if c in df.columns]].copy()

    # Build sample weights from failure records — upweights rows where model was wrong
    sample_weights = build_failure_sample_weights(df)

    folds = build_walk_forward_folds(df, feature_cols, label_col, scale=scale,
                                     sample_weights=sample_weights)

    dataset = TrainingDataset(
        df           = df,
        feature_cols = feature_cols,
        label_col    = label_col,
        folds        = folds,
    )

    log.info(
        "Dataset ready: %d rows, %d features, %d folds, label=%s",
        len(df), len(feature_cols), len(folds), label_col,
    )
    return dataset


def get_final_train_test(
    dataset: TrainingDataset,
    test_fraction: float = 0.20,
    scale: bool = True,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series, Optional[RobustScaler], Optional[pd.Series]]:
    """
    Simple chronological train/test split of the full dataset.
    Used for final model training after walk-forward validation.

    Returns: X_train, y_train, X_test, y_test, scaler, train_sample_weights
    train_sample_weights is None when no failure records exist (safe to ignore).
    """
    df   = dataset.df.sort_values("date").reset_index(drop=True)
    feat = dataset.feature_cols
    lbl  = dataset.label_col

    split_idx = int(len(df) * (1 - test_fraction))
    train = df.iloc[:split_idx]
    test  = df.iloc[split_idx:]

    X_train = train[feat].copy()
    y_train = train[lbl].copy()
    X_test  = test[feat].copy()
    y_test  = test[lbl].copy()

    scaler = None
    if scale:
        scaler  = RobustScaler()
        X_train = pd.DataFrame(scaler.fit_transform(X_train), columns=feat, index=X_train.index)
        X_test  = pd.DataFrame(scaler.transform(X_test),      columns=feat, index=X_test.index)

    # Build failure-upweighted sample weights for the training split
    train_weights = build_failure_sample_weights(train)
    if train_weights is not None and train_weights.sum() == len(train):
        # All weights equal 1.0 means no failure records — pass None so callers skip the overhead
        train_weights = None

    return X_train, y_train, X_test, y_test, scaler, train_weights

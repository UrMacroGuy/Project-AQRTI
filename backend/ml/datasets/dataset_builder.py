"""
AQRTI Dataset Builder
Joins feature vectors from feature_store with forward-looking labels.

Temporal ordering is enforced throughout:
  - Features for date t are computed from data UP TO t
  - Labels for date t are computed from data AFTER t
  - The join key is (symbol, date) — only rows present in BOTH are kept
  - No shuffling before the chronological split
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db
from aqrti.database.models import DailyPrice, IndexData, Stock
from aqrti.utils.logger import get_logger
from ml.datasets.label_generator import generate_labels, clip_label_outliers, LABEL_COLUMNS

log = get_logger("dataset_builder")

# Minimum feature completeness ratio — rows with more than this fraction
# of NaN feature values are dropped
MAX_NAN_RATIO = 0.30

# Minimum rows per symbol to include it in training
MIN_ROWS_PER_SYMBOL = 50


def _load_price_data(db: Session, symbol: str, days: int = 2000) -> pd.DataFrame:
    """Load daily close prices for a symbol, sorted ascending."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(DailyPrice.date, DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff)
        .order_by(DailyPrice.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame(rows, columns=["date", "close"])


def _load_nifty_data(db: Session, days: int = 2000) -> pd.DataFrame:
    """Load NIFTY50 daily close prices, sorted ascending."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(IndexData.date, IndexData.close)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff)
        .order_by(IndexData.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame(rows, columns=["date", "close"])


def _load_feature_vectors(db: Session, symbol: str, version: int = 1) -> pd.DataFrame:
    """
    Load all feature vectors for a symbol from feature_values table.
    Returns DataFrame: rows=dates, columns=feature_names.
    """
    from aqrti.database.models import FeatureValue
    rows = (
        db.query(FeatureValue.date, FeatureValue.feature_name, FeatureValue.value)
        .filter(FeatureValue.symbol == symbol, FeatureValue.version == version)
        .order_by(FeatureValue.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame()

    records = [{"date": r.date, "feature": r.feature_name, "value": r.value} for r in rows]
    df = pd.DataFrame(records)
    pivoted = df.pivot(index="date", columns="feature", values="value")
    pivoted.columns.name = None
    pivoted = pivoted.reset_index()
    return pivoted


def build_symbol_dataset(
    db: Session,
    symbol: str,
    version: int = 1,
) -> Optional[pd.DataFrame]:
    """
    Build a fully labeled, feature-joined dataset for one symbol.

    Returns DataFrame with columns:
      - symbol
      - date
      - [all feature columns]
      - [all label columns]

    Returns None if insufficient data.
    """
    price_df = _load_price_data(db, symbol)
    nifty_df = _load_nifty_data(db)
    feat_df  = _load_feature_vectors(db, symbol, version)

    if price_df.empty or feat_df.empty:
        log.debug("Skipping %s — missing price or feature data", symbol)
        return None

    # Generate forward labels from raw prices (no leakage)
    labels_df = generate_labels(price_df, nifty_df)
    labels_df = clip_label_outliers(labels_df)

    if labels_df.empty:
        log.debug("Skipping %s — no labeled rows", symbol)
        return None

    # Align types for merge
    feat_df["date"]   = pd.to_datetime(feat_df["date"]).dt.date
    labels_df["date"] = pd.to_datetime(labels_df["date"]).dt.date

    # Inner join on date — only dates with BOTH features AND labels
    merged = feat_df.merge(labels_df, on="date", how="inner")

    if len(merged) < MIN_ROWS_PER_SYMBOL:
        log.debug("Skipping %s — only %d joined rows (min %d)", symbol, len(merged), MIN_ROWS_PER_SYMBOL)
        return None

    # Drop rows where too many features are NaN
    # Use get_feature_columns to also exclude _x/_y label merge artifacts
    feature_cols = get_feature_columns(merged)
    nan_ratio = merged[feature_cols].isnull().mean(axis=1)
    merged = merged[nan_ratio <= MAX_NAN_RATIO].copy()

    if len(merged) < MIN_ROWS_PER_SYMBOL:
        log.debug("Skipping %s — only %d rows after NaN filter", symbol, len(merged))
        return None

    # Drop any _x/_y label merge artifacts that would cause data leakage
    leaky_cols = []
    for lbl in LABEL_COLUMNS:
        for suffix in ("_x", "_y"):
            col = f"{lbl}{suffix}"
            if col in merged.columns:
                leaky_cols.append(col)
    if leaky_cols:
        merged = merged.drop(columns=leaky_cols)

    merged.insert(0, "symbol", symbol)
    merged = merged.sort_values("date").reset_index(drop=True)
    return merged


def build_full_dataset(version: int = 1) -> pd.DataFrame:
    """
    Build the complete multi-symbol labeled dataset.

    Returns combined DataFrame sorted by date (then symbol).
    Uses all active stocks in the DB (not just hardcoded universe).
    """
    all_dfs = []
    with get_db() as db:
        # Use all active symbols that have price data
        symbols = [
            row[0] for row in
            db.query(Stock.symbol).filter(Stock.active == True).all()
        ]
        log.info("Building dataset for %d active symbols", len(symbols))
        for symbol in symbols:
            df = build_symbol_dataset(db, symbol, version)
            if df is not None:
                all_dfs.append(df)
                log.info("Built dataset for %s: %d rows", symbol, len(df))
            else:
                log.debug("No dataset for %s", symbol)

    if not all_dfs:
        log.error("No symbol datasets could be built")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)

    log.info(
        "Full dataset: %d rows, %d symbols, date range %s to %s",
        len(combined),
        combined["symbol"].nunique(),
        combined["date"].min(),
        combined["date"].max(),
    )
    return combined


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return feature column names (exclude symbol, date, label columns and their merge suffixes)."""
    # Build exclusion set: exact labels + _x/_y suffixes produced by pd.merge when both sides have the same column
    excluded = {"symbol", "date"}
    for lbl in LABEL_COLUMNS:
        excluded.update({lbl, f"{lbl}_x", f"{lbl}_y"})
    return [c for c in df.columns if c not in excluded]


def fill_feature_nans(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill remaining NaN feature values using forward-fill then median.
    Applied per-symbol to respect temporal ordering.
    """
    feature_cols = get_feature_columns(df)
    result = df.copy()

    # Forward-fill within each symbol (temporal imputation)
    result[feature_cols] = (
        result.groupby("symbol")[feature_cols]
        .transform(lambda x: x.ffill())
    )

    # Fill remaining NaNs with cross-sectional median for that column
    for col in feature_cols:
        if result[col].isnull().any():
            median = result[col].median()
            result[col] = result[col].fillna(median if not np.isnan(median) else 0.0)

    return result

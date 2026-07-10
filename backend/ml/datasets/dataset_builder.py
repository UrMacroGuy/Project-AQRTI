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
from ml.datasets.label_generator import generate_labels, LABEL_COLUMNS

log = get_logger("dataset_builder")

# Minimum feature completeness ratio — rows with more than this fraction
# of NaN feature values are dropped
MAX_NAN_RATIO = 0.30

# Minimum rows per symbol to include it in training
MIN_ROWS_PER_SYMBOL = 50


def _load_price_data(db: Session, symbol: str, days: int = 2000) -> pd.DataFrame:
    """Load daily OHLC prices for a symbol, sorted ascending."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(DailyPrice.date, DailyPrice.close, DailyPrice.high, DailyPrice.low)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff)
        .order_by(DailyPrice.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["date", "close", "high", "low"])
    df = pd.DataFrame(rows, columns=["date", "close", "high", "low"])
    # Fill missing high/low with close (some older rows may lack them)
    df["high"] = df["high"].fillna(df["close"])
    df["low"]  = df["low"].fillna(df["close"])
    return df


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


def _load_feature_vectors(db: Session, symbol: str, version: int = 1, days: Optional[int] = None) -> pd.DataFrame:
    """
    Load feature vectors for a symbol from feature_values table.
    Returns DataFrame: rows=dates, columns=feature_names.

    days: if given, only load feature vectors from the last N calendar days
    (keeps training-window restrictions RAM-friendly by not pulling full
    history into memory just to discard it after the date filter).
    """
    from aqrti.database.models import FeatureValue
    query = (
        db.query(FeatureValue.date, FeatureValue.feature_name, FeatureValue.value)
        .filter(FeatureValue.symbol == symbol, FeatureValue.version == version)
    )
    if days is not None:
        cutoff = date.today() - timedelta(days=days)
        query = query.filter(FeatureValue.date >= cutoff)
    rows = query.order_by(FeatureValue.date.asc()).all()
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
    days_back: Optional[int] = None,
) -> Optional[pd.DataFrame]:
    """
    Build a fully labeled, feature-joined dataset for one symbol.

    Returns DataFrame with columns:
      - symbol
      - date
      - [all feature columns]
      - [all label columns]

    days_back: if given, restrict to the last N calendar days of history
    (both price/feature loading AND the min-rows check below account for
    this — see build_full_dataset for the min-rows adjustment).

    Returns None if insufficient data.
    """
    # Pad the price/nifty load window so forward-looking labels (direction_5d
    # needs 5 future trading days) can still be computed for rows near the
    # end of the requested window, and so early rows in the window have
    # enough trailing history for rolling-window features.
    load_days = (days_back + 15) if days_back is not None else 2000
    price_df = _load_price_data(db, symbol, days=load_days)
    nifty_df = _load_nifty_data(db, days=load_days)
    feat_df  = _load_feature_vectors(db, symbol, version, days=days_back)

    if price_df.empty or feat_df.empty:
        log.debug("Skipping %s — missing price or feature data", symbol)
        return None

    # Generate forward labels from raw prices (no leakage)
    labels_df = generate_labels(price_df, nifty_df)

    if labels_df.empty:
        log.debug("Skipping %s — no labeled rows", symbol)
        return None

    # Align types for merge
    feat_df["date"]   = pd.to_datetime(feat_df["date"]).dt.date
    labels_df["date"] = pd.to_datetime(labels_df["date"]).dt.date

    # Inner join on date — only dates with BOTH features AND labels
    merged = feat_df.merge(labels_df, on="date", how="inner")

    min_rows = MIN_ROWS_PER_SYMBOL
    if len(merged) < min_rows:
        log.debug("Skipping %s — only %d joined rows (min %d)", symbol, len(merged), min_rows)
        return None

    # Drop rows where too many features are NaN
    # Use get_feature_columns to also exclude _x/_y label merge artifacts
    feature_cols = get_feature_columns(merged)
    nan_ratio = merged[feature_cols].isnull().mean(axis=1)
    merged = merged[nan_ratio <= MAX_NAN_RATIO].copy()

    if len(merged) < min_rows:
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


DEFAULT_TRAINING_WINDOW_DAYS = 150  # 2026-07-07 policy: train on recent data only.
                                    # Was 90 (~62-63 trading days) but measured
                                    # end-to-end (price -> features -> forward
                                    # labels -> inner join) only ~48 usable
                                    # rows/symbol survived — BELOW MIN_ROWS_PER_SYMBOL=50,
                                    # so build_full_dataset silently dropped ~678/679
                                    # symbols and training collapsed to ~1 symbol.
                                    # 150 days (~100 trading days) measured at
                                    # ~81-86 usable rows/symbol across a random
                                    # 30-symbol sample — real margin above the floor.
                                    # Still much smaller than full 2021->now history
                                    # per symbol, so the original RAM-saving intent
                                    # is preserved.


def build_full_dataset(version: int = 1, days_back: Optional[int] = DEFAULT_TRAINING_WINDOW_DAYS) -> pd.DataFrame:
    """
    Build the complete multi-symbol labeled dataset.

    Returns combined DataFrame sorted by date (then symbol).
    Uses all active stocks in the DB (not just hardcoded universe).

    days_back: restrict to the last N calendar days (default 90 — recent-data-
    only training policy, 2026-07-07). Pass None for full history (e.g. one-off
    research/comparison scripts that intentionally want the whole dataset).
    """
    all_dfs = []
    with get_db() as db:
        # Use all active symbols that have price data
        symbols = [
            row[0] for row in
            db.query(Stock.symbol).filter(Stock.active == True).all()
        ]
        log.info("Building dataset for %d active symbols (days_back=%s)", len(symbols), days_back)
        for symbol in symbols:
            df = build_symbol_dataset(db, symbol, version, days_back=days_back)
            if df is not None:
                all_dfs.append(df)
                log.debug("Built dataset for %s: %d rows", symbol, len(df))
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

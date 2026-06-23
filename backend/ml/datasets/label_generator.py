"""
AQRTI Label Generator
Generates forward-looking labels for ML training.

NO DATA LEAKAGE GUARANTEE:
  - Label for date t uses close prices at t+N (future)
  - Features for date t use only data up to and including t
  - Forward prices are looked up from the same price DataFrame,
    sorted chronologically, using integer position offsets
  - No row is labeled if the required forward price does not exist
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger

log = get_logger("label_generator")

# Forward horizons in trading days
HORIZONS = [3, 5, 10, 15]

# Columns produced (order matters for downstream consumers)
LABEL_COLUMNS = [
    "return_3d",
    "return_5d",
    "return_10d",
    "return_15d",
    "outperform_nifty_5d",    # stock_return_5d - nifty_return_5d
    "direction_5d",            # 1 if return_5d > 0 else 0
    "outperform_binary",       # 1 if outperform_nifty_5d > 0 else 0
    "expected_return",         # average of 5d + 10d returns (medium-term view)
]


def generate_labels(
    price_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Given a price DataFrame for ONE symbol (columns: date, close) and a
    NIFTY DataFrame (columns: date, close), return a DataFrame with one
    row per date containing all forward-looking labels.

    Rows where forward prices do not exist are DROPPED (not filled).

    Args:
        price_df:  DataFrame sorted by date ascending; must have 'date' and 'close'
        nifty_df:  DataFrame sorted by date ascending; must have 'date' and 'close'

    Returns:
        DataFrame with columns ['date'] + LABEL_COLUMNS, no NaN label rows.
    """
    if price_df.empty or len(price_df) < max(HORIZONS) + 1:
        return pd.DataFrame(columns=["date"] + LABEL_COLUMNS)

    df = price_df.copy().reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)

    nifty = nifty_df.copy().reset_index(drop=True)
    nifty["date"] = pd.to_datetime(nifty["date"]).dt.date
    nifty = nifty.sort_values("date").reset_index(drop=True)

    # Build NIFTY close lookup by date for fast O(1) access
    nifty_close: dict[date, float] = dict(zip(nifty["date"], nifty["close"]))

    records = []
    closes = df["close"].values
    dates  = df["date"].values
    n      = len(df)

    for i in range(n):
        row_date  = dates[i]
        close_t   = closes[i]

        if close_t is None or close_t <= 0 or np.isnan(close_t):
            continue

        # Compute all horizon returns — skip row if any forward price is missing
        horizon_returns: dict[int, float] = {}
        skip = False
        for h in HORIZONS:
            if i + h >= n:
                skip = True
                break
            close_th = closes[i + h]
            if close_th is None or close_th <= 0 or np.isnan(close_th):
                skip = True
                break
            horizon_returns[h] = (close_th / close_t) - 1.0

        if skip:
            continue

        # NIFTY 5d return for outperformance label
        nifty_close_t  = nifty_close.get(row_date)
        nifty_close_t5 = None
        if i + 5 < n:
            future_date = dates[i + 5]
            nifty_close_t5 = nifty_close.get(future_date)

        if nifty_close_t and nifty_close_t5 and nifty_close_t > 0:
            nifty_return_5d = (nifty_close_t5 / nifty_close_t) - 1.0
        else:
            nifty_return_5d = None

        r3  = horizon_returns[3]
        r5  = horizon_returns[5]
        r10 = horizon_returns[10]
        r15 = horizon_returns[15]

        outperform_nifty_5d = (r5 - nifty_return_5d) if nifty_return_5d is not None else None
        direction_5d        = 1 if r5 > 0 else 0
        outperform_binary   = (1 if outperform_nifty_5d > 0 else 0) if outperform_nifty_5d is not None else None
        expected_return     = (r5 + r10) / 2.0

        records.append({
            "date":               row_date,
            "return_3d":          round(r3  * 100, 4),
            "return_5d":          round(r5  * 100, 4),
            "return_10d":         round(r10 * 100, 4),
            "return_15d":         round(r15 * 100, 4),
            "outperform_nifty_5d": round(outperform_nifty_5d * 100, 4) if outperform_nifty_5d is not None else None,
            "direction_5d":       direction_5d,
            "outperform_binary":  outperform_binary,
            "expected_return":    round(expected_return * 100, 4),
        })

    result = pd.DataFrame(records, columns=["date"] + LABEL_COLUMNS)
    # Drop rows where any critical label is null
    result = result.dropna(subset=["return_5d", "direction_5d", "expected_return"])
    log.debug("Generated %d labeled rows from %d price rows", len(result), n)
    return result


def clip_label_outliers(labels_df: pd.DataFrame, sigma: float = 3.0) -> pd.DataFrame:
    """
    Clip continuous label columns at ±sigma standard deviations.
    Binary columns (direction_5d, outperform_binary) are NOT clipped.
    """
    df = labels_df.copy()
    continuous = ["return_3d", "return_5d", "return_10d", "return_15d",
                  "outperform_nifty_5d", "expected_return"]
    for col in continuous:
        if col not in df.columns:
            continue
        mean = df[col].mean()
        std  = df[col].std()
        if std > 0:
            df[col] = df[col].clip(mean - sigma * std, mean + sigma * std)
    return df

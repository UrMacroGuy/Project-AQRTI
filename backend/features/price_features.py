"""
AQRTI Price Features
Computes all price-category features for a given symbol's OHLCV DataFrame.
Input: DataFrame with columns [date, open, high, low, close, volume, daily_return]
       sorted ascending by date.
Output: dict {feature_name: value} for the LAST row (most recent date).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_price_features(df: pd.DataFrame, nifty_df: Optional[pd.DataFrame] = None) -> dict:
    """
    Compute all price features for the most recent date in df.
    nifty_df: optional NIFTY50 price DataFrame with same date range.
    Returns dict of {feature_name: float|None}.
    """
    if df.empty or len(df) < 2:
        return {}

    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]
    n = len(df)

    results: dict[str, Optional[float]] = {}

    # return_1d
    results["return_1d"] = _pct_change(close, 1)

    # return_5d
    results["return_5d"] = _pct_change(close, 5)

    # return_21d
    results["return_21d"] = _pct_change(close, 21)

    # return_63d
    results["return_63d"] = _pct_change(close, 63)

    # momentum_10d
    results["momentum_10d"] = _pct_change(close, 10)

    # momentum_20d
    results["momentum_20d"] = _pct_change(close, 20)

    # gap_open_pct: (open_today - close_yesterday) / close_yesterday * 100
    if "open" in df.columns and n >= 2:
        prev_close = close.iloc[-2]
        curr_open  = df["open"].iloc[-1]
        results["gap_open_pct"] = _safe_divide(curr_open - prev_close, prev_close) * 100
    else:
        results["gap_open_pct"] = None

    # breakout_distance_52w: (close - 52w_high) / 52w_high * 100  (negative = below)
    if n >= 252:
        high_52w = close.iloc[-252:].max()
        results["breakout_distance_52w"] = _safe_divide(
            close.iloc[-1] - high_52w, high_52w
        ) * 100
    elif n >= 20:
        high_window = close.max()
        results["breakout_distance_52w"] = _safe_divide(
            close.iloc[-1] - high_window, high_window
        ) * 100
    else:
        results["breakout_distance_52w"] = None

    # support_distance_20d: (close - 20d_low) / 20d_low * 100
    if n >= 20 and "low" in df.columns:
        low_20d = df["low"].iloc[-20:].min()
        results["support_distance_20d"] = _safe_divide(
            close.iloc[-1] - low_20d, low_20d
        ) * 100
    else:
        results["support_distance_20d"] = None

    # resistance_distance_20d: (20d_high - close) / close * 100
    if n >= 20 and "high" in df.columns:
        high_20d = df["high"].iloc[-20:].max()
        results["resistance_distance_20d"] = _safe_divide(
            high_20d - close.iloc[-1], close.iloc[-1]
        ) * 100
    else:
        results["resistance_distance_20d"] = None

    # price_position_52w: (close - 52w_low) / (52w_high - 52w_low)
    window = min(252, n)
    if window >= 20:
        lo = close.iloc[-window:].min()
        hi = close.iloc[-window:].max()
        span = hi - lo
        results["price_position_52w"] = _safe_divide(close.iloc[-1] - lo, span)
    else:
        results["price_position_52w"] = None

    # relative_strength_nifty_21d
    if nifty_df is not None and not nifty_df.empty and n >= 22:
        nifty_df = nifty_df.sort_values("date").reset_index(drop=True)
        nifty_close = nifty_df["close"]
        nifty_ret21 = _pct_change(nifty_close, 21)
        stock_ret21 = results.get("return_21d")
        if nifty_ret21 is not None and stock_ret21 is not None:
            results["relative_strength_nifty_21d"] = stock_ret21 - nifty_ret21
        else:
            results["relative_strength_nifty_21d"] = None
    else:
        results["relative_strength_nifty_21d"] = None

    return {k: _round(v) for k, v in results.items()}


# ── Helpers ───────────────────────────────────────────────────
def _pct_change(series: pd.Series, periods: int) -> Optional[float]:
    n = len(series)
    if n <= periods:
        return None
    prev = series.iloc[-(periods + 1)]
    curr = series.iloc[-1]
    if prev == 0 or pd.isna(prev) or pd.isna(curr):
        return None
    return (curr / prev - 1) * 100


def _safe_divide(num: float, den: float) -> float:
    if den == 0 or pd.isna(den) or pd.isna(num):
        return 0.0
    return num / den


def _round(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), 6)

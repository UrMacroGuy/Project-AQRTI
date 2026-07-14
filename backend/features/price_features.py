"""
AQRTI Price Features
Computes all price-category features for a given symbol's OHLCV DataFrame.
Input: DataFrame with columns [date, open, high, low, close, volume, daily_return]
       sorted ascending by date.
Output: dict {feature_name: value} for the LAST row (most recent date).
"""

from __future__ import annotations

import math

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

    # return_126d — 6-month return, the horizon behind the 52-week-high
    # momentum evidence (docs/STRATEGY_LAB.md variant D: 6m return > 10%
    # confirmation; Jegadeesh-Titman 6-12mo momentum replicates on NSE per
    # CLAUDE.md's India evidence). Same pattern as return_63d.
    results["return_126d"] = _pct_change(close, 126)

    # tom_window — turn-of-month flag: 1 if this date is among the FIRST 3
    # trading days of its calendar month, else 0. NSE turn-of-month days
    # carry ~4x the average daily return (CLAUDE.md India evidence, window
    # [-1,+2]). The T-1 leg (last trading day of the month) is deliberately
    # EXCLUDED: knowing d is the month's last trading day requires knowing
    # the next trading day — future calendar knowledge relative to the
    # expanding data slice this function receives. Counting how many
    # trading rows of the current month exist in the slice up to and
    # including d is fully point-in-time.
    last_date = pd.Timestamp(df["date"].iloc[-1])
    periods = pd.to_datetime(df["date"]).dt.to_period("M")
    month_mask = periods == last_date.to_period("M")
    trading_days_this_month = int(month_mask.sum())
    # Guard: the slice must actually contain the month boundary (at least
    # one bar from an earlier month), otherwise a symbol whose history
    # STARTS mid-month would falsely flag its first 3 bars as
    # turn-of-month. If every bar in the slice is from the current month,
    # we cannot know how many trading days the month already had -> 0.
    saw_prior_month = bool((~month_mask).any())
    results["tom_window"] = 1.0 if (saw_prior_month and trading_days_this_month <= 3) else 0.0

    # trend_tstat_63d — t-statistic of the 63-day drift:
    #   mean(daily returns) / std(daily returns) * sqrt(63)
    # i.e. the in-window Sharpe of the trend scaled to the window length.
    # This is the statistically-honest trend filter: |t| >= ~1.7 means the
    # drift is distinguishable from zero at ~90% confidence, so entries
    # conditioned on it buy MEASURED trend, not noise. It is the natural
    # DSL-expressible form of vol-scaled time-series momentum (Moskowitz,
    # Ooi & Pedersen 2012), since the DSL cannot divide two features.
    # Point-in-time: uses only the trailing 64 closes in the slice.
    if n >= 64:
        rets = close.iloc[-64:].pct_change().dropna()
        std = float(rets.std())
        results["trend_tstat_63d"] = (
            round(float(rets.mean()) / std * math.sqrt(63), 4) if std > 0 else 0.0
        )
    else:
        results["trend_tstat_63d"] = None

    # momentum_10d: acceleration = recent 5d return minus prior 5d return
    # Measures whether momentum is accelerating (positive) or decelerating (negative)
    results["momentum_10d"] = _momentum_accel(close, fast=5, slow=10)

    # momentum_20d: acceleration = recent 10d return minus prior 10d return
    results["momentum_20d"] = _momentum_accel(close, fast=10, slow=20)

    # gap_open_pct: (open_today - close_yesterday) / close_yesterday * 100
    if "open" in df.columns and n >= 2:
        prev_close = close.iloc[-2]
        curr_open  = df["open"].iloc[-1]
        results["gap_open_pct"] = _safe_divide(curr_open - prev_close, prev_close) * 100
    else:
        results["gap_open_pct"] = None

    # breakout_distance_52w: (close - 52w_high) / 52w_high * 100  (negative = below high)
    # Only compute when we have true 252-day window — fallback to None avoids misleading values
    if n >= 252:
        high_52w = close.iloc[-252:].max()
        results["breakout_distance_52w"] = _safe_divide(
            close.iloc[-1] - high_52w, high_52w
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
def _momentum_accel(series: pd.Series, fast: int, slow: int) -> Optional[float]:
    """Momentum acceleration: return over last `fast` bars minus return over prior `fast` bars.
    Prior window ends `slow` bars ago. Positive = accelerating, negative = decelerating."""
    n = len(series)
    required = slow + fast + 1
    if n < required:
        return None
    recent_ret = _pct_change(series.iloc[-(fast + 1):], fast)
    # Prior window: fast+1 bars ending at index -(slow+1) (i.e., slow bars ago)
    end_idx   = n - slow        # exclusive end → closes at series[end_idx - 1]
    start_idx = end_idx - fast - 1
    prior_ret = _pct_change(series.iloc[start_idx:end_idx], fast)
    if recent_ret is None or prior_ret is None:
        return None
    return recent_ret - prior_ret


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
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 6)
    except (TypeError, ValueError):
        return None

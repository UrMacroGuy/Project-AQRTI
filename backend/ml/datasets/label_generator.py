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
    "direction_barrier",       # triple-barrier: 1=UP hit TP, 0=DOWN hit SL, None=neutral (dropped)
]

# Triple-barrier label parameters
# TP = 1.5 × ATR14 (or pct fallback), SL = 1.0 × ATR14, max hold = 10 bars
BARRIER_TP_ATR_MULT  = 1.5
BARRIER_SL_ATR_MULT  = 1.0
BARRIER_MAX_HOLD     = 10
# Fallback fixed pct barriers when ATR is unavailable
BARRIER_TP_PCT_FIXED = 0.015   # 1.5%
BARRIER_SL_PCT_FIXED = 0.010   # 1.0%


def _triple_barrier_label(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    i: int,
    tp_pct: float,
    sl_pct: float,
    max_hold: int = BARRIER_MAX_HOLD,
) -> Optional[int]:
    """
    Label row i using the triple-barrier method.

    Returns:
        1    if the TP barrier is hit before SL within max_hold bars
        0    if the SL barrier is hit before TP within max_hold bars
        None if neither barrier is hit (NEUTRAL — caller drops these rows)

    Uses intrabar high/low so we can detect which barrier was hit first
    when both are breached on the same bar (TP wins on an up bar, SL on a down bar).
    """
    c0 = closes[i]
    tp = c0 * (1.0 + tp_pct)
    sl = c0 * (1.0 - sl_pct)

    for j in range(1, max_hold + 1):
        k = i + j
        if k >= len(closes):
            break
        h = highs[k] if highs is not None and k < len(highs) else closes[k]
        l = lows[k]  if lows  is not None and k < len(lows)  else closes[k]
        # Check intrabar: if high hits TP and low hits SL on same bar,
        # determine which came first by close direction
        hit_tp = h >= tp
        hit_sl = l <= sl
        if hit_tp and hit_sl:
            return 1 if closes[k] >= c0 else 0
        if hit_tp:
            return 1
        if hit_sl:
            return 0
    return None  # NEUTRAL


def generate_labels(
    price_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Given a price DataFrame for ONE symbol (columns: date, close[, high, low]) and a
    NIFTY DataFrame (columns: date, close), return a DataFrame with one
    row per date containing all forward-looking labels.

    Rows where forward prices do not exist are DROPPED (not filled).
    direction_barrier rows where neither barrier is hit are set to None
    (callers that use this label should dropna on it separately).

    Args:
        price_df:  DataFrame sorted by date ascending; must have 'date' and 'close';
                   optionally 'high' and 'low' for better barrier computation.
        nifty_df:  DataFrame sorted by date ascending; must have 'date' and 'close'

    Returns:
        DataFrame with columns ['date'] + LABEL_COLUMNS, no NaN on core labels.
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

    closes = df["close"].values
    highs  = df["high"].values  if "high" in df.columns else None
    lows   = df["low"].values   if "low"  in df.columns else None
    dates  = df["date"].values
    n      = len(df)

    # Pre-compute ATR14 for dynamic barrier sizing
    # TR = max(high-low, |high-prev_close|, |low-prev_close|)
    atr14 = np.full(n, np.nan)
    if highs is not None and lows is not None:
        for i in range(1, n):
            h, l, pc = highs[i], lows[i], closes[i - 1]
            if not (np.isnan(h) or np.isnan(l) or np.isnan(pc)):
                tr = max(h - l, abs(h - pc), abs(l - pc))
                window_start = max(0, i - 13)
                # Use simple rolling mean of TR over last 14 bars
                trs = []
                for k in range(window_start, i + 1):
                    hk, lk = highs[k], lows[k]
                    pck = closes[k - 1] if k > 0 else closes[k]
                    if not (np.isnan(hk) or np.isnan(lk) or np.isnan(pck)):
                        trs.append(max(hk - lk, abs(hk - pck), abs(lk - pck)))
                if trs:
                    atr14[i] = np.mean(trs)

    records = []

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

        # Triple-barrier label — use ATR-based barriers when available
        if not np.isnan(atr14[i]) and atr14[i] > 0:
            tp_pct = (BARRIER_TP_ATR_MULT * atr14[i]) / close_t
            sl_pct = (BARRIER_SL_ATR_MULT * atr14[i]) / close_t
        else:
            tp_pct = BARRIER_TP_PCT_FIXED
            sl_pct = BARRIER_SL_PCT_FIXED
        # Cap barriers at 8% to avoid unreachable thresholds for low-vol stocks
        tp_pct = min(tp_pct, 0.08)
        sl_pct = min(sl_pct, 0.06)

        direction_barrier = _triple_barrier_label(closes, highs, lows, i, tp_pct, sl_pct)

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
            "direction_barrier":  direction_barrier,   # None = NEUTRAL, will be dropna'd by callers
        })

    result = pd.DataFrame(records, columns=["date"] + LABEL_COLUMNS)
    # Drop rows where core labels are null (direction_barrier nulls are kept for callers to handle)
    result = result.dropna(subset=["return_5d", "direction_5d", "expected_return"])
    log.debug(
        "Generated %d labeled rows from %d price rows (%d barrier-neutral)",
        len(result), n,
        result["direction_barrier"].isna().sum(),
    )
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

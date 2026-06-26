"""
AQRTI Volatility Features
Input: DataFrame with [date, open, high, low, close, volume] sorted ascending.
       Optional nifty_df for beta computation (must be date-aligned before passing).
Output: dict {feature_name: value} for the last row.

FIXES applied:
  - rolling_vol: use pre-computed log_returns slice, not close ratio broadcasting
  - beta: align stock/nifty by date before slicing (fixes date-mismatch bug)
  - inf values clamped in _round
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_volatility_features(
    df: pd.DataFrame,
    nifty_df: Optional[pd.DataFrame] = None,
) -> dict:
    if df.empty or len(df) < 11:
        return {}

    df    = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    n     = len(df)

    # Compute log returns once — single source of truth for all vol calcs
    log_ret = np.log(close.values[1:] / close.values[:-1])   # length n-1

    results: dict[str, Optional[float]] = {}

    # ── ATR 14 ───────────────────────────────────────────────────
    if n >= 15 and "high" in df.columns and "low" in df.columns:
        results["atr_14"]     = _compute_atr(df, 14)
        results["atr_pct_14"] = (
            _safe_divide(results["atr_14"], float(close.iloc[-1])) * 100
            if results["atr_14"] is not None else None
        )
    else:
        results["atr_14"]     = None
        results["atr_pct_14"] = None

    # ── rolling_vol_10d ──────────────────────────────────────────
    # Uses last 10 log returns (requires 11 prices = 10 returns)
    if len(log_ret) >= 10:
        r10 = log_ret[-10:]
        results["rolling_vol_10d"] = float(np.std(r10, ddof=1) * np.sqrt(252) * 100)
    else:
        results["rolling_vol_10d"] = None

    # ── rolling_vol_21d ──────────────────────────────────────────
    if len(log_ret) >= 21:
        r21 = log_ret[-21:]
        results["rolling_vol_21d"] = float(np.std(r21, ddof=1) * np.sqrt(252) * 100)
    else:
        results["rolling_vol_21d"] = None

    # ── historical_vol_63d ───────────────────────────────────────
    if len(log_ret) >= 63:
        r63 = log_ret[-63:]
        results["historical_vol_63d"] = float(np.std(r63, ddof=1) * np.sqrt(252) * 100)
    else:
        results["historical_vol_63d"] = None

    # ── vol_expansion / vol_compression ─────────────────────────
    v10 = results.get("rolling_vol_10d")
    v21 = results.get("rolling_vol_21d")
    if v10 is not None and v21 is not None and v21 > 0:
        results["vol_expansion"]   = 1.0 if v10 > v21 * 1.2 else 0.0
        results["vol_compression"] = 1.0 if v10 < v21 * 0.8 else 0.0
    else:
        results["vol_expansion"]   = None
        results["vol_compression"] = None

    # ── beta_21d vs NIFTY (date-aligned) ────────────────────────
    if nifty_df is not None and not nifty_df.empty and n >= 22:
        results["beta_21d"] = _compute_beta_aligned(df, nifty_df, window=21)
    else:
        results["beta_21d"] = None

    return {k: _round(v) for k, v in results.items()}


# ── Helpers ───────────────────────────────────────────────────
def _compute_atr(df: pd.DataFrame, period: int) -> Optional[float]:
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    n = len(close)
    if n < period + 1:
        return None
    tr_list = []
    for i in range(1, n):
        hl  = high[i] - low[i]
        hpc = abs(high[i] - close[i - 1])
        lpc = abs(low[i] - close[i - 1])
        tr_list.append(max(hl, hpc, lpc))
    tr = np.array(tr_list[-period:])
    return float(np.mean(tr))


def _compute_beta_aligned(
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    window: int = 21,
) -> Optional[float]:
    """
    Align stock and nifty on shared trading dates before computing beta.
    This prevents date-mismatch corruption.
    """
    # Normalise date columns
    s = stock_df[["date", "close"]].copy()
    n = nifty_df[["date", "close"]].copy()
    s["date"] = pd.to_datetime(s["date"]).dt.date
    n["date"] = pd.to_datetime(n["date"]).dt.date

    merged = pd.merge(s, n, on="date", suffixes=("_stock", "_nifty")).sort_values("date")
    if len(merged) < window + 1:
        return None

    # Use last window+1 aligned rows
    tail = merged.tail(window + 1)
    s_vals = tail["close_stock"].astype(float).values
    n_vals = tail["close_nifty"].astype(float).values

    if np.any(s_vals <= 0) or np.any(n_vals <= 0):
        return None

    s_ret = np.diff(np.log(s_vals))
    n_ret = np.diff(np.log(n_vals))
    if len(s_ret) < 2:
        return None

    cov = np.cov(s_ret, n_ret)[0][1]
    var = float(np.var(n_ret, ddof=1))
    return _safe_divide(cov, var)


def _safe_divide(num, den) -> float:
    try:
        n, d = float(num), float(den)
        if d == 0 or np.isnan(d) or np.isnan(n) or np.isinf(n) or np.isinf(d):
            return 0.0
        return n / d
    except Exception:
        return 0.0


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

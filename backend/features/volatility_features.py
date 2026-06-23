"""
AQRTI Volatility Features
Input: DataFrame with [date, open, high, low, close, volume] sorted ascending.
       Optional nifty_df for beta computation.
Output: dict {feature_name: value} for the last row.
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

    df = df.sort_values("date").reset_index(drop=True)
    close  = df["close"]
    n      = len(df)
    log_returns = np.log(close / close.shift(1)).dropna()

    results: dict[str, Optional[float]] = {}

    # ATR_14
    if n >= 15 and "high" in df.columns and "low" in df.columns:
        results["atr_14"] = _compute_atr(df, 14)
        results["atr_pct_14"] = (
            _safe_divide(results["atr_14"], float(close.iloc[-1])) * 100
            if results["atr_14"] is not None else None
        )
    else:
        results["atr_14"]     = None
        results["atr_pct_14"] = None

    # rolling_vol_10d: annualised std of daily log returns, 10-day window
    if n >= 11:
        r = np.log(close.values[-11:] / close.values[-12:-1]) if n >= 12 else log_returns.values[-10:]
        results["rolling_vol_10d"] = float(np.std(r, ddof=1) * np.sqrt(252) * 100) if len(r) >= 2 else None
    else:
        results["rolling_vol_10d"] = None

    # rolling_vol_21d
    if n >= 22:
        r = np.log(close.values[-22:] / close.values[-23:-1]) if n >= 23 else log_returns.values[-21:]
        results["rolling_vol_21d"] = float(np.std(r, ddof=1) * np.sqrt(252) * 100) if len(r) >= 2 else None
    else:
        results["rolling_vol_21d"] = None

    # historical_vol_63d
    if n >= 64:
        r = log_returns.values[-63:]
        results["historical_vol_63d"] = float(np.std(r, ddof=1) * np.sqrt(252) * 100)
    else:
        results["historical_vol_63d"] = None

    # vol_expansion / vol_compression
    v10 = results.get("rolling_vol_10d")
    v21 = results.get("rolling_vol_21d")
    if v10 is not None and v21 is not None and v21 > 0:
        results["vol_expansion"]  = 1.0 if v10 > v21 * 1.2 else 0.0
        results["vol_compression"] = 1.0 if v10 < v21 * 0.8 else 0.0
    else:
        results["vol_expansion"]   = None
        results["vol_compression"] = None

    # beta_21d vs NIFTY
    if nifty_df is not None and not nifty_df.empty and n >= 22:
        results["beta_21d"] = _compute_beta(close, nifty_df["close"], window=21)
    else:
        results["beta_21d"] = None

    return {k: _round(v) for k, v in results.items()}


# ── Helpers ───────────────────────────────────────────────────
def _compute_atr(df: pd.DataFrame, period: int) -> Optional[float]:
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
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


def _compute_beta(
    stock_close: pd.Series,
    nifty_close: pd.Series,
    window: int = 21,
) -> Optional[float]:
    min_len = min(len(stock_close), len(nifty_close))
    if min_len < window + 1:
        return None
    s_vals = stock_close.values[-window - 1:].astype(float)
    n_vals = nifty_close.values[-window - 1:].astype(float)
    if len(s_vals) < window + 1 or len(n_vals) < window + 1:
        return None
    s_ret = np.diff(np.log(s_vals))
    n_ret = np.diff(np.log(n_vals))
    if len(s_ret) < 2:
        return None
    cov = np.cov(s_ret, n_ret)[0][1]
    var = np.var(n_ret, ddof=1)
    return _safe_divide(cov, var)


def _safe_divide(num, den) -> float:
    try:
        if den == 0 or pd.isna(den) or pd.isna(num):
            return 0.0
        return float(num) / float(den)
    except Exception:
        return 0.0


def _round(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None

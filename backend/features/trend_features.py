"""
AQRTI Trend Features
EMA, SMA, MACD, RSI, ADX computed from OHLCV DataFrame.
Input: DataFrame with [date, open, high, low, close] sorted ascending.
Output: dict {feature_name: value} for the last row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_trend_features(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 9:
        return {}

    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    n     = len(close)

    results: dict[str, Optional[float]] = {}

    # ── EMA ──────────────────────────────────────────────────
    for span in (9, 21, 50, 200):
        key = f"ema_{span}"
        if n >= span:
            results[key] = _ema(close, span)
        else:
            results[key] = None

    # ── SMA ──────────────────────────────────────────────────
    for w in (20, 50):
        key = f"sma_{w}"
        results[key] = float(close.iloc[-w:].mean()) if n >= w else None

    # ── Price vs EMA % ───────────────────────────────────────
    for span in (21, 50):
        ema_val = results.get(f"ema_{span}")
        key     = f"price_vs_ema{span}_pct"
        if ema_val and ema_val != 0:
            results[key] = (float(close.iloc[-1]) - ema_val) / ema_val * 100
        else:
            results[key] = None

    # ── MACD ─────────────────────────────────────────────────
    if n >= 35:
        ema12 = _ema_series(close, 12)
        ema26 = _ema_series(close, 26)
        macd  = ema12 - ema26
        sig   = _ema_series(macd, 9)
        hist  = macd - sig

        results["macd_line"]      = float(macd.iloc[-1])
        results["macd_signal"]    = float(sig.iloc[-1])
        results["macd_histogram"] = float(hist.iloc[-1])

        # crossover: +1 bullish (hist went -→+), -1 bearish, 0 none
        if len(hist) >= 2:
            h1 = hist.iloc[-2]
            h2 = hist.iloc[-1]
            if h1 < 0 and h2 >= 0:
                results["macd_crossover"] = 1.0
            elif h1 > 0 and h2 <= 0:
                results["macd_crossover"] = -1.0
            else:
                results["macd_crossover"] = 0.0
        else:
            results["macd_crossover"] = 0.0
    else:
        for k in ("macd_line", "macd_signal", "macd_histogram", "macd_crossover"):
            results[k] = None

    # ── RSI 14 ───────────────────────────────────────────────
    if n >= 15:
        results["rsi_14"] = _rsi(close, 14)
    else:
        results["rsi_14"] = None

    # rsi_divergence: 1 if price up 5d but RSI down 5d (bearish), -1 opposite, 0 none
    if n >= 20:
        rsi_now  = results.get("rsi_14")
        rsi_prev = _rsi(close.iloc[:-5], 14) if n >= 20 else None
        ret5     = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) if n >= 6 else None
        if rsi_now is not None and rsi_prev is not None and ret5 is not None:
            if ret5 > 0 and rsi_now < rsi_prev:
                results["rsi_divergence"] = 1.0   # bearish divergence
            elif ret5 < 0 and rsi_now > rsi_prev:
                results["rsi_divergence"] = -1.0  # bullish divergence
            else:
                results["rsi_divergence"] = 0.0
        else:
            results["rsi_divergence"] = None
    else:
        results["rsi_divergence"] = None

    # ── ADX 14 ───────────────────────────────────────────────
    if n >= 28 and "high" in df.columns and "low" in df.columns:
        adx_val, di_diff = _adx(df["high"].astype(float), df["low"].astype(float), close, 14)
        results["adx_14"]        = adx_val
        results["di_plus_minus"] = di_diff
    else:
        results["adx_14"]        = None
        results["di_plus_minus"] = None

    return {k: _round(v) for k, v in results.items()}


# ── Computation Helpers ───────────────────────────────────────
def _ema(series: pd.Series, span: int) -> Optional[float]:
    if len(series) < span:
        return None
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _ema_series(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    # Wilder's smoothing
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def _adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> tuple[Optional[float], Optional[float]]:
    n = len(close)
    if n < period * 2:
        return None, None

    tr_arr, dm_plus, dm_minus = [], [], []
    h = high.values
    l = low.values
    c = close.values

    for i in range(1, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        tr_arr.append(tr)

        up_move   = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]

        dm_plus.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        dm_minus.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    tr_s  = pd.Series(tr_arr)
    dmp_s = pd.Series(dm_plus)
    dmm_s = pd.Series(dm_minus)

    atr14  = tr_s.ewm(alpha=1 / period, adjust=False).mean()
    dip14  = dmp_s.ewm(alpha=1 / period, adjust=False).mean()
    dim14  = dmm_s.ewm(alpha=1 / period, adjust=False).mean()

    atr_val = atr14.iloc[-1]
    if atr_val == 0:
        return None, None

    di_plus  = float(dip14.iloc[-1] / atr_val * 100)
    di_minus = float(dim14.iloc[-1] / atr_val * 100)
    dx       = abs(di_plus - di_minus) / (di_plus + di_minus) * 100 if (di_plus + di_minus) > 0 else 0.0

    dx_series = pd.Series(
        [abs(dip14.iloc[i] - dim14.iloc[i]) / (dip14.iloc[i] + dim14.iloc[i]) * 100
         if (dip14.iloc[i] + dim14.iloc[i]) > 0 else 0.0
         for i in range(len(dip14))]
    )
    adx_val = float(dx_series.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])

    return adx_val, di_plus - di_minus


def _round(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None

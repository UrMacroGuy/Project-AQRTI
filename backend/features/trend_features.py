"""
AQRTI Trend Features
EMA, SMA, MACD, RSI, ADX computed from OHLCV DataFrame.
Input: DataFrame with [date, open, high, low, close] sorted ascending.
Output: dict {feature_name: value} for the last row.

FIXES applied:
  - RSI divergence: compare RSI(close[:-5]) vs RSI(close) on same-length window
    to avoid mixing different EMA warm-up depths
  - MACD: require n >= 60 (not 35) so EMA26+EMA9 have >2x their span to converge
  - EMA: warn-safe (still computed but flagged with fewer rows)
  - inf values caught in _round
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_trend_features(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 9:
        return {}

    df    = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    n     = len(close)

    results: dict[str, Optional[float]] = {}

    # ── EMA ──────────────────────────────────────────────────────
    ema_cache: dict[int, Optional[float]] = {}
    for span in (9, 21, 50, 200):
        key = f"ema_{span}"
        if n >= span:
            val = _ema(close, span)
            results[key]        = val
            ema_cache[span]     = val
        else:
            results[key]        = None
            ema_cache[span]     = None

    # ── SMA ──────────────────────────────────────────────────────
    sma20_val: Optional[float] = None
    sma50_val: Optional[float] = None
    for w in (20, 50):
        if n >= w:
            val = float(close.iloc[-w:].mean())
            results[f"sma_{w}"] = val
            if w == 20:
                sma20_val = val
            else:
                sma50_val = val
        else:
            results[f"sma_{w}"] = None

    curr_close = float(close.iloc[-1])

    # ── MA Slopes (% change of MA over 5 bars) ──────────────────
    # slope = (MA_now - MA_5bars_ago) / MA_5bars_ago * 100
    # Used by rl_momentum family strategies
    if n >= 25:
        sma20_prev = float(close.iloc[-25:-5].mean())  # SMA20 computed ending 5 bars ago
        results["ma_20_slope"] = (sma20_val - sma20_prev) / sma20_prev * 100 if sma20_val and sma20_prev else None
    else:
        results["ma_20_slope"] = None

    if n >= 55:
        sma50_prev = float(close.iloc[-55:-5].mean())  # SMA50 computed ending 5 bars ago
        results["ma_50_slope"] = (sma50_val - sma50_prev) / sma50_prev * 100 if sma50_val and sma50_prev else None
    else:
        results["ma_50_slope"] = None

    # ── MA Spread: (SMA20 - SMA50) / SMA50 * 100 ────────────────
    if sma20_val and sma50_val and sma50_val != 0:
        results["ma_spread"] = (sma20_val - sma50_val) / sma50_val * 100
    else:
        results["ma_spread"] = None

    # ── Close vs MA diff (%) ─────────────────────────────────────
    if sma20_val and sma20_val != 0:
        results["close_ma20_diff"] = (curr_close - sma20_val) / sma20_val * 100
    else:
        results["close_ma20_diff"] = None
    if sma50_val and sma50_val != 0:
        results["close_ma50_diff"] = (curr_close - sma50_val) / sma50_val * 100
    else:
        results["close_ma50_diff"] = None

    # ── Price vs EMA % ───────────────────────────────────────────
    for span in (21, 50, 200):
        ema_val = ema_cache.get(span)
        if ema_val and ema_val != 0:
            results[f"price_vs_ema{span}_pct"] = (curr_close - ema_val) / ema_val * 100
        else:
            results[f"price_vs_ema{span}_pct"] = None

    # ── MACD ─────────────────────────────────────────────────────
    # Need EMA(26) + EMA(9) of MACD line to converge — require 60 bars minimum
    if n >= 60:
        ema12  = _ema_series(close, 12)
        ema26  = _ema_series(close, 26)
        macd   = ema12 - ema26
        sig    = _ema_series(macd, 9)
        hist   = macd - sig

        results["macd_line"]      = float(macd.iloc[-1])
        results["macd_signal"]    = float(sig.iloc[-1])
        results["macd_histogram"] = float(hist.iloc[-1])

        if len(hist) >= 2:
            h1, h2 = hist.iloc[-2], hist.iloc[-1]
            if   h1 < 0 and h2 >= 0: results["macd_crossover"] =  1.0  # bullish
            elif h1 > 0 and h2 <= 0: results["macd_crossover"] = -1.0  # bearish
            else:                     results["macd_crossover"] =  0.0
        else:
            results["macd_crossover"] = 0.0
    else:
        for k in ("macd_line", "macd_signal", "macd_histogram", "macd_crossover"):
            results[k] = None

    # ── RSI 14 ───────────────────────────────────────────────────
    if n >= 15:
        results["rsi_14"] = _rsi(close, 14)
    else:
        results["rsi_14"] = None

    # ── RSI Divergence ───────────────────────────────────────────
    # Compare RSI computed on same rolling 15-bar window ending at t vs t-5.
    # Both use identical EMA warm-up depth — no bias.
    results["rsi_divergence"] = None
    if n >= 25:   # need 15-bar RSI window + 5-bar lookback + some buffer
        rsi_now  = _rsi(close.iloc[-15:], 14)      # RSI on most recent 15 bars
        rsi_prev = _rsi(close.iloc[-20:-5], 14)    # RSI on window ending 5 bars ago
        ret5 = (curr_close - float(close.iloc[-6])) / float(close.iloc[-6]) if n >= 6 else None

        if rsi_now is not None and rsi_prev is not None and ret5 is not None:
            if   ret5 > 0 and rsi_now < rsi_prev:  results["rsi_divergence"] =  1.0  # bearish divergence
            elif ret5 < 0 and rsi_now > rsi_prev:  results["rsi_divergence"] = -1.0  # bullish divergence
            else:                                   results["rsi_divergence"] =  0.0

    # ── ADX 14 ───────────────────────────────────────────────────
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
    """Wilder RSI. Requires exactly period+1 rows minimum."""
    if len(close) < period + 1:
        return None
    delta    = close.diff().dropna()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
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

    h = high.values.astype(float)
    l = low.values.astype(float)
    c = close.values.astype(float)

    tr_arr, dm_plus, dm_minus = [], [], []
    for i in range(1, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        tr_arr.append(tr)
        up_move   = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]
        dm_plus.append(up_move   if up_move   > down_move and up_move   > 0 else 0.0)
        dm_minus.append(down_move if down_move > up_move   and down_move > 0 else 0.0)

    tr_s  = pd.Series(tr_arr)
    dmp_s = pd.Series(dm_plus)
    dmm_s = pd.Series(dm_minus)

    atr14 = tr_s.ewm(alpha=1 / period,  adjust=False).mean()
    dip14 = dmp_s.ewm(alpha=1 / period, adjust=False).mean()
    dim14 = dmm_s.ewm(alpha=1 / period, adjust=False).mean()

    atr_val = float(atr14.iloc[-1])
    if atr_val == 0:
        return None, None

    di_plus  = float(dip14.iloc[-1] / atr_val * 100)
    di_minus = float(dim14.iloc[-1] / atr_val * 100)

    dx_series = pd.Series([
        abs(dip14.iloc[i] - dim14.iloc[i]) / (dip14.iloc[i] + dim14.iloc[i]) * 100
        if (dip14.iloc[i] + dim14.iloc[i]) > 0 else 0.0
        for i in range(len(dip14))
    ])
    adx_val = float(dx_series.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])

    return adx_val, di_plus - di_minus


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

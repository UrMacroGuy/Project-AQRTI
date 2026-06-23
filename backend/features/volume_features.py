"""
AQRTI Volume Features
Input: DataFrame with [date, open, high, low, close, volume, delivery_volume] sorted ascending.
Output: dict {feature_name: value} for the last row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_volume_features(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 5:
        return {}

    df = df.sort_values("date").reset_index(drop=True)
    close  = df["close"]
    volume = df["volume"] if "volume" in df.columns else None
    n      = len(df)

    if volume is None or volume.isna().all():
        return {}

    results: dict[str, Optional[float]] = {}

    # volume_ratio_5d
    if n >= 5:
        avg5 = volume.iloc[-5:].mean()
        results["volume_ratio_5d"] = _safe_divide(volume.iloc[-1], avg5)
    else:
        results["volume_ratio_5d"] = None

    # volume_ratio_20d
    if n >= 20:
        avg20 = volume.iloc[-20:].mean()
        results["volume_ratio_20d"] = _safe_divide(volume.iloc[-1], avg20)
    else:
        results["volume_ratio_20d"] = None

    # relative_volume: percentile rank of today's volume in last 63 days
    if n >= 63:
        window = volume.iloc[-63:].values
        today  = volume.iloc[-1]
        results["relative_volume"] = float(np.sum(window <= today)) / len(window) * 100
    elif n >= 20:
        window = volume.iloc[-n:].values
        today  = volume.iloc[-1]
        results["relative_volume"] = float(np.sum(window <= today)) / len(window) * 100
    else:
        results["relative_volume"] = None

    # volume_spike: 1 if today volume > 2x 20d avg
    if n >= 20:
        avg20 = volume.iloc[-20:].mean()
        results["volume_spike"] = 1.0 if volume.iloc[-1] > 2.0 * avg20 else 0.0
    else:
        results["volume_spike"] = None

    # accumulation_score_5d: fraction of last 5 days where close > open, weighted by volume
    if n >= 5 and "open" in df.columns:
        sub = df.iloc[-5:]
        up_vol   = sub.loc[sub["close"] > sub["open"], "volume"].sum()
        tot_vol  = sub["volume"].sum()
        results["accumulation_score_5d"] = _safe_divide(up_vol, tot_vol)
    else:
        results["accumulation_score_5d"] = None

    # distribution_score_5d: fraction of last 5 days where close < open, weighted by volume
    if n >= 5 and "open" in df.columns:
        sub = df.iloc[-5:]
        dn_vol  = sub.loc[sub["close"] < sub["open"], "volume"].sum()
        tot_vol = sub["volume"].sum()
        results["distribution_score_5d"] = _safe_divide(dn_vol, tot_vol)
    else:
        results["distribution_score_5d"] = None

    # obv_slope_10d: slope of On-Balance Volume over last 10 days, normalised by close
    if n >= 11:
        obv  = _compute_obv(close.values, volume.values)
        obv_last10 = obv[-10:]
        x = np.arange(10, dtype=float)
        slope, _ = np.polyfit(x, obv_last10, 1)
        results["obv_slope_10d"] = _safe_divide(slope, float(close.iloc[-1]))
    else:
        results["obv_slope_10d"] = None

    # delivery_ratio
    if "delivery_volume" in df.columns and not df["delivery_volume"].isna().all():
        dv = df["delivery_volume"].iloc[-1]
        tv = volume.iloc[-1]
        results["delivery_ratio"] = _safe_divide(dv, tv)
    else:
        results["delivery_ratio"] = None

    return {k: _round(v) for k, v in results.items()}


# ── Helpers ───────────────────────────────────────────────────
def _compute_obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    obv = np.zeros(len(close))
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def _safe_divide(num, den) -> float:
    if den == 0 or den is None or pd.isna(den) or pd.isna(num):
        return 0.0
    return float(num) / float(den)


def _round(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), 6)

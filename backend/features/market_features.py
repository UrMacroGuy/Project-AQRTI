"""
AQRTI Market & Sector Features
Computes cross-sectional features: NIFTY relative strength, sector rank, breadth.
Requires universe-wide data so it operates on a dict of DataFrames.

compute_market_features(symbol, stock_df, nifty_df, universe_dfs, sector_map)
  → dict {feature_name: value}
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_market_features(
    symbol: str,
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    universe_dfs: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
) -> dict:
    """
    symbol       : the target stock symbol
    stock_df     : OHLCV DataFrame for symbol (sorted ascending)
    nifty_df     : NIFTY50 OHLCV DataFrame (sorted ascending)
    universe_dfs : {symbol: DataFrame} for all stocks in universe
    sector_map   : {symbol: sector_name}
    """
    results: dict[str, Optional[float]] = {}
    stock_df = stock_df.sort_values("date").reset_index(drop=True)
    n = len(stock_df)

    # ── NIFTY relative features ───────────────────────────────
    if not nifty_df.empty:
        nifty_df = nifty_df.sort_values("date").reset_index(drop=True)

        results["nifty_return_5d"]  = _pct_change(nifty_df["close"], 5)
        results["nifty_return_21d"] = _pct_change(nifty_df["close"], 21)

        stock_ret21 = _pct_change(stock_df["close"], 21)
        nifty_ret21 = results["nifty_return_21d"]
        if stock_ret21 is not None and nifty_ret21 is not None:
            results["nifty_rs_21d"] = stock_ret21 - nifty_ret21
        else:
            results["nifty_rs_21d"] = None

        results["nifty_beta_daily"] = _compute_beta(stock_df["close"], nifty_df["close"], 21)
    else:
        for k in ("nifty_return_5d", "nifty_return_21d", "nifty_rs_21d", "nifty_beta_daily"):
            results[k] = None

    # ── Breadth indicators (universe-wide) ───────────────────
    above_ema50_count  = 0
    above_ema200_count = 0
    valid_count        = 0

    for sym, df in universe_dfs.items():
        if df.empty or len(df) < 50:
            continue
        valid_count += 1
        c = df["close"].astype(float)
        ema50  = float(c.ewm(span=50,  adjust=False).mean().iloc[-1])
        if len(c) >= 200:
            ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
        else:
            ema200 = None
        curr   = float(c.iloc[-1])
        if curr > ema50:
            above_ema50_count += 1
        if ema200 is not None and curr > ema200:
            above_ema200_count += 1

    if valid_count > 0:
        results["breadth_pct_above_ema50"]  = above_ema50_count  / valid_count * 100
        results["breadth_pct_above_ema200"] = above_ema200_count / valid_count * 100
    else:
        results["breadth_pct_above_ema50"]  = None
        results["breadth_pct_above_ema200"] = None

    # ── Sector-relative features ──────────────────────────────
    own_sector = sector_map.get(symbol)
    peers = [s for s, sec in sector_map.items() if sec == own_sector and s != symbol]
    peer_dfs = {s: universe_dfs[s] for s in peers if s in universe_dfs}

    peer_ret21: list[float] = []
    peer_vol21: list[float] = []

    for s, df in peer_dfs.items():
        r = _pct_change(df["close"], 21)
        if r is not None:
            peer_ret21.append(r)
        v = _rolling_vol(df["close"], 21)
        if v is not None:
            peer_vol21.append(v)

    stock_ret21 = _pct_change(stock_df["close"], 21)
    stock_vol21 = _rolling_vol(stock_df["close"], 21)

    if peer_ret21:
        sector_avg_ret21 = float(np.mean(peer_ret21))
        results["sector_return_5d"]  = _sector_avg_ret(peer_dfs, 5)
        results["sector_return_21d"] = sector_avg_ret21

        if stock_ret21 is not None:
            results["sector_rs_21d"] = stock_ret21 - sector_avg_ret21
            # rank: 1 = best in sector
            all_rets = sorted([stock_ret21] + peer_ret21, reverse=True)
            results["sector_rank"] = float(all_rets.index(stock_ret21) + 1)
            results["peer_rank_return_21d"] = float(all_rets.index(stock_ret21) + 1)
        else:
            results["sector_rs_21d"]        = None
            results["sector_rank"]          = None
            results["peer_rank_return_21d"] = None
    else:
        for k in ("sector_return_5d", "sector_return_21d", "sector_rs_21d",
                  "sector_rank", "peer_rank_return_21d"):
            results[k] = None

    if peer_vol21:
        sector_avg_vol21 = float(np.mean(peer_vol21))
        all_vols = sorted([v for v in ([stock_vol21] if stock_vol21 else []) + peer_vol21])
        if stock_vol21 is not None:
            results["peer_rank_vol"] = float(all_vols.index(stock_vol21) + 1)
            results["relative_vol_vs_sector"] = _safe_divide(stock_vol21, sector_avg_vol21)
        else:
            results["peer_rank_vol"]           = None
            results["relative_vol_vs_sector"]  = None
    else:
        results["peer_rank_vol"]           = None
        results["relative_vol_vs_sector"]  = None

    return {k: _round(v) for k, v in results.items()}


# ── Helpers ───────────────────────────────────────────────────
def _pct_change(series: pd.Series, periods: int) -> Optional[float]:
    n = len(series)
    if n <= periods:
        return None
    prev = float(series.iloc[-(periods + 1)])
    curr = float(series.iloc[-1])
    if prev == 0 or pd.isna(prev) or pd.isna(curr):
        return None
    return (curr / prev - 1) * 100


def _rolling_vol(series: pd.Series, window: int) -> Optional[float]:
    if len(series) < window + 1:
        return None
    log_ret = np.log(series.astype(float).values[-window - 1:])
    diffs = np.diff(log_ret)
    if len(diffs) < 2:
        return None
    return float(np.std(diffs, ddof=1) * np.sqrt(252) * 100)


def _sector_avg_ret(peer_dfs: dict[str, pd.DataFrame], periods: int) -> Optional[float]:
    rets = []
    for df in peer_dfs.values():
        r = _pct_change(df["close"], periods)
        if r is not None:
            rets.append(r)
    return float(np.mean(rets)) if rets else None


def _compute_beta(
    stock_close: pd.Series,
    nifty_close: pd.Series,
    window: int = 21,
) -> Optional[float]:
    min_len = min(len(stock_close), len(nifty_close))
    if min_len < window + 1:
        return None
    s_vals = stock_close.astype(float).values[-window - 1:]
    n_vals = nifty_close.astype(float).values[-window - 1:]
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

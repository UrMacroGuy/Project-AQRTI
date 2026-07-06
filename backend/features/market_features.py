"""
AQRTI Market & Sector Features
Computes cross-sectional features: NIFTY relative strength, sector rank, breadth.

FIXES applied:
  - sector_rank / peer_rank_return_21d: use bisect for tie-safe ranking
  - peer_rank_vol: same tie-safe approach
  - beta: date-align stock and nifty before slicing (prevents date-mismatch)
  - breadth: document that it's fraction of universe with sufficient history
  - inf values caught in _round
"""

from __future__ import annotations

import bisect
import numpy as np
import pandas as pd
from typing import Optional


def compute_market_features(
    symbol: str,
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    universe_dfs: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    breadth_snapshot: Optional[dict[str, tuple]] = None,
) -> dict:
    """
    breadth_snapshot: optional {symbol: (close, ema50_or_None, ema200_or_None)}
    precomputed by the caller for the CURRENT date across the whole universe.
    When provided, breadth is computed from this O(1) lookup instead of
    recomputing ewm(span=50/200).mean() from scratch for all 352 symbols on
    every single date (that recomputation was ~45% of total backfill runtime
    — EMA is a recursive expanding-window stat, its value at date T doesn't
    need the full history recomputed every time a later date is processed).
    When None (e.g. run_symbol_features' single-date on-demand path), falls
    back to the original in-place computation — identical formula either way.
    """
    results: dict[str, Optional[float]] = {}
    stock_df = stock_df.sort_values("date").reset_index(drop=True)

    # ── NIFTY relative features ───────────────────────────────
    if not nifty_df.empty:
        nifty_df = nifty_df.sort_values("date").reset_index(drop=True)

        results["nifty_return_5d"]  = _pct_change(nifty_df["close"], 5)
        results["nifty_return_21d"] = _pct_change(nifty_df["close"], 21)

        stock_ret21 = _pct_change(stock_df["close"], 21)
        nifty_ret21 = results["nifty_return_21d"]
        results["nifty_rs_21d"] = (
            stock_ret21 - nifty_ret21
            if stock_ret21 is not None and nifty_ret21 is not None else None
        )
        results["nifty_beta_daily"] = _compute_beta_aligned(stock_df, nifty_df, 21)
    else:
        for k in ("nifty_return_5d", "nifty_return_21d", "nifty_rs_21d", "nifty_beta_daily"):
            results[k] = None

    # ── Breadth indicators (universe-wide) ───────────────────
    above_ema50_count  = 0
    above_ema200_count = 0
    valid_ema50_count  = 0
    valid_ema200_count = 0

    if breadth_snapshot is not None:
        for sym, (curr, ema50, ema200) in breadth_snapshot.items():
            if ema50 is not None:
                valid_ema50_count += 1
                if curr > ema50:
                    above_ema50_count += 1
            if ema200 is not None:
                valid_ema200_count += 1
                if curr > ema200:
                    above_ema200_count += 1
    else:
        for sym, df in universe_dfs.items():
            if df.empty:
                continue
            c = df["close"].astype(float)
            curr = float(c.iloc[-1])
            if len(c) >= 50:
                ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
                valid_ema50_count += 1
                if curr > ema50:
                    above_ema50_count += 1
            if len(c) >= 200:
                ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
                valid_ema200_count += 1
                if curr > ema200:
                    above_ema200_count += 1

    results["breadth_pct_above_ema50"]  = (
        above_ema50_count  / valid_ema50_count  * 100 if valid_ema50_count  > 0 else None
    )
    results["breadth_pct_above_ema200"] = (
        above_ema200_count / valid_ema200_count * 100 if valid_ema200_count > 0 else None
    )

    # ── Sector-relative features ──────────────────────────────
    own_sector = sector_map.get(symbol)
    peers      = [s for s, sec in sector_map.items() if sec == own_sector and s != symbol]
    peer_dfs   = {s: universe_dfs[s] for s in peers if s in universe_dfs}

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
        sector_avg_ret21            = float(np.mean(peer_ret21))
        results["sector_return_5d"]  = _sector_avg_ret(peer_dfs, 5)
        results["sector_return_21d"] = sector_avg_ret21

        if stock_ret21 is not None:
            results["sector_rs_21d"] = stock_ret21 - sector_avg_ret21
            # Tie-safe rank: use bisect on descending-sorted list
            rank = _rank_desc(stock_ret21, peer_ret21)
            total = len(peer_ret21) + 1
            results["sector_rank"]          = round(rank / total * 100, 1)
            results["peer_rank_return_21d"] = int(rank)
        else:
            results["sector_rs_21d"]        = None
            results["sector_rank"]          = None
            results["peer_rank_return_21d"] = None
    else:
        for k in ("sector_return_5d", "sector_return_21d", "sector_rs_21d",
                  "sector_rank", "peer_rank_return_21d"):
            results[k] = None

    if peer_vol21 and stock_vol21 is not None:
        sector_avg_vol21                   = float(np.mean(peer_vol21))
        results["peer_rank_vol"]           = float(_rank_asc(stock_vol21, peer_vol21))
        results["relative_vol_vs_sector"]  = _safe_divide(stock_vol21, sector_avg_vol21)
    else:
        results["peer_rank_vol"]           = None
        results["relative_vol_vs_sector"]  = None

    return {k: _round(v) for k, v in results.items()}


# ── Helpers ───────────────────────────────────────────────────
def _rank_desc(value: float, peers: list[float]) -> int:
    """Rank of `value` among [value]+peers in descending order. 1 = highest. Tie-safe."""
    all_vals = sorted(peers + [value], reverse=True)
    # bisect on negated list (ascending) for tie safety
    neg = sorted(-(v) for v in (peers + [value]))
    return bisect.bisect_left(neg, -value) + 1


def _rank_asc(value: float, peers: list[float]) -> int:
    """Rank of `value` among [value]+peers in ascending order. 1 = lowest. Tie-safe."""
    all_vals = sorted(peers + [value])
    return bisect.bisect_left(all_vals, value) + 1


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
    vals = series.astype(float).values[-(window + 1):]
    if np.any(vals <= 0):
        return None
    diffs = np.diff(np.log(vals))
    if len(diffs) < 2:
        return None
    return float(np.std(diffs, ddof=1) * np.sqrt(252) * 100)


def _sector_avg_ret(peer_dfs: dict[str, pd.DataFrame], periods: int) -> Optional[float]:
    rets = [r for df in peer_dfs.values() if (r := _pct_change(df["close"], periods)) is not None]
    return float(np.mean(rets)) if rets else None


def _compute_beta_aligned(
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    window: int = 21,
) -> Optional[float]:
    """Align stock and nifty on shared trading dates before computing beta."""
    s = stock_df[["date", "close"]].copy()
    n = nifty_df[["date", "close"]].copy()
    s["date"] = pd.to_datetime(s["date"]).dt.date
    n["date"] = pd.to_datetime(n["date"]).dt.date

    merged = pd.merge(s, n, on="date", suffixes=("_s", "_n")).sort_values("date")
    if len(merged) < window + 1:
        return None

    tail  = merged.tail(window + 1)
    s_v   = tail["close_s"].astype(float).values
    n_v   = tail["close_n"].astype(float).values

    if np.any(s_v <= 0) or np.any(n_v <= 0):
        return None

    s_ret = np.diff(np.log(s_v))
    n_ret = np.diff(np.log(n_v))
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

"""
AQRTI Feature Generator — Orchestrator
Runs all feature modules for all symbols, writes results to feature_store.
Supports:
  - Full run: all symbols × all available dates
  - Incremental run: only new dates since last computed
  - Single-symbol run: for testing or on-demand
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db
from aqrti.database.models import DailyPrice, IndexData, Stock
from aqrti.config.settings import get_settings
from aqrti.utils.logger import get_logger

from features.price_features      import compute_price_features
from features.volume_features     import compute_volume_features
from features.volatility_features import compute_volatility_features
from features.trend_features      import compute_trend_features
from features.market_features     import compute_market_features
from features.fii_features        import compute_fii_dii_features, load_fii_dii_cache, FIIDIICache
from features.feature_store       import save_feature_vector, get_last_computed_date
from features.feature_registry    import seed_feature_metadata

_EMA_MIN_ROWS = {"ema50": 50, "ema200": 200}

log = get_logger("feature_generator")

# Minimum rows of price history required before generating features
MIN_HISTORY_ROWS = 30


# ══════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINTS
# ══════════════════════════════════════════════════════════════
def run_full_feature_generation(version: int = 1, only_symbols: Optional[set] = None) -> dict:
    """
    Compute features for every symbol in the universe for every date that
    has price data but no stored features yet.
    only_symbols: restrict regeneration to these symbols (market features
    still use the full universe for breadth/sector context).
    Returns summary report.
    """
    log.info("=== FULL FEATURE GENERATION STARTED (only=%s) ===",
             sorted(only_symbols) if only_symbols else "ALL")
    with get_db() as db:
        seed_feature_metadata(db)
        universe_dfs, nifty_df, sector_map = _load_universe_data(db)
        report = _generate_all(db, universe_dfs, nifty_df, sector_map,
                               version=version, only_symbols=only_symbols)
    log.info("=== FEATURE GENERATION COMPLETE: %s ===", report)
    return report


def run_incremental_feature_generation(version: int = 1) -> dict:
    """
    Compute features only for dates after the last computed date per symbol.
    Safe to run daily after market data ingestion.
    """
    log.info("=== INCREMENTAL FEATURE GENERATION STARTED ===")
    with get_db() as db:
        seed_feature_metadata(db)
        universe_dfs, nifty_df, sector_map = _load_universe_data(db)
        report = _generate_incremental(db, universe_dfs, nifty_df, sector_map, version=version)
    log.info("=== INCREMENTAL GENERATION COMPLETE: %s ===", report)
    return report


def run_symbol_features(symbol: str, version: int = 1) -> dict[str, Optional[float]]:
    """
    Compute the latest feature vector for a single symbol.
    Returns the feature dict (does NOT write to DB).
    Useful for testing and on-demand API calls.
    """
    with get_db() as db:
        universe_dfs, nifty_df, sector_map = _load_universe_data(db)
        if symbol not in universe_dfs:
            return {}
        universe_dfs = {s: _normalize_dates(df) for s, df in universe_dfs.items()}
        nifty_df     = _normalize_dates(nifty_df)
        stock_df = universe_dfs[symbol]
        return _compute_all_features(symbol, stock_df, nifty_df, universe_dfs, sector_map)


# ══════════════════════════════════════════════════════════════
# INTERNAL: data loading
# ══════════════════════════════════════════════════════════════
def _load_universe_data(
    db: Session,
    days: int = 2000,   # must stay >= actual DailyPrice history depth (currently
                         # ~5yr / 1830 days back to 2021-06-29) or feature coverage
                         # silently truncates and the fail-closed backtester blocks
                         # entries across the missing window. Was 1200 (~3.3yr) —
                         # left ~23 months of price history with zero features.
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, str]]:
    """
    Load price history for all universe stocks + NIFTY50.
    Returns (universe_dfs, nifty_df, sector_map).
    """
    cutoff   = date.today() - timedelta(days=days)

    # Load stock data — use ALL active symbols that have price data (not just settings list)
    universe_dfs: dict[str, pd.DataFrame] = {}
    sector_map: dict[str, str] = {}

    stocks = db.query(Stock).filter(Stock.active == True).all()
    for stock in stocks:
        sector_map[stock.symbol] = stock.sector or "Unknown"
        rows = (
            db.query(DailyPrice)
            .filter(DailyPrice.symbol == stock.symbol, DailyPrice.date >= cutoff)
            .order_by(DailyPrice.date.asc())
            .all()
        )
        if rows:
            df_tmp = pd.DataFrame([
                {
                    "date":            r.date,
                    "open":            pd.to_numeric(r.open, errors="coerce"),
                    "high":            pd.to_numeric(r.high, errors="coerce"),
                    "low":             pd.to_numeric(r.low, errors="coerce"),
                    "close":           pd.to_numeric(r.close, errors="coerce"),
                    "volume":          pd.to_numeric(r.volume, errors="coerce"),
                    "delivery_volume": pd.to_numeric(r.delivery_volume, errors="coerce"),
                    "daily_return":    pd.to_numeric(r.daily_return, errors="coerce"),
                }
                for r in rows
            ])
            # Drop rows with no close price — feature modules require valid close
            df_tmp = df_tmp.dropna(subset=["close"]).reset_index(drop=True)
            if not df_tmp.empty:
                universe_dfs[stock.symbol] = df_tmp

    # Load NIFTY50
    nifty_rows = (
        db.query(IndexData)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff)
        .order_by(IndexData.date.asc())
        .all()
    )
    nifty_df = pd.DataFrame([
        {"date": r.date,
         "close":   pd.to_numeric(r.close, errors="coerce"),
         "returns": pd.to_numeric(r.returns, errors="coerce")}
        for r in nifty_rows
    ]).dropna(subset=["close"]).reset_index(drop=True) if nifty_rows else pd.DataFrame()

    log.info("Loaded %d symbols, %d NIFTY rows.", len(universe_dfs), len(nifty_df))
    return universe_dfs, nifty_df, sector_map


# ══════════════════════════════════════════════════════════════
# INTERNAL: per-symbol feature computation
# ══════════════════════════════════════════════════════════════
def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure all numeric columns are float dtype (None -> NaN). Call ONCE on
    a full (unsliced) DataFrame — never on an .iloc[] view, which would risk
    writing into the parent frame's buffer (SettingWithCopyWarning territory)
    and corrupting other date-slices sharing the same underlying array."""
    if df.empty:
        return df
    num_cols = ["open", "high", "low", "close", "volume", "delivery_volume", "daily_return"]
    df = df.copy()
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _compute_all_features(
    symbol: str,
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    universe_dfs: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    breadth_snapshot: Optional[dict[str, tuple]] = None,
    fii_dii_cache: Optional[FIIDIICache] = None,
    peer_mean_snapshot: Optional[dict[str, dict]] = None,
) -> dict[str, Optional[float]]:
    """Merge all feature category outputs into one flat dict. Callers must
    pass already-numeric-coerced DataFrames (see _coerce_numeric) — this
    function no longer mutates its inputs, since slices may be read-only
    views into a larger, shared, pre-sliced frame.

    Optional:
      fii_dii_cache:     FIIDIICache instance pre-loaded for this run
      peer_mean_snapshot: {symbol: {"peer_mean_momentum_10d": val, ...}} for P2-A
    """
    features: dict[str, Optional[float]] = {}

    features.update(compute_price_features(stock_df, nifty_df))
    features.update(compute_volume_features(stock_df))
    features.update(compute_volatility_features(stock_df, nifty_df))
    features.update(compute_trend_features(stock_df))
    features.update(compute_market_features(symbol, stock_df, nifty_df, universe_dfs, sector_map,
                                            breadth_snapshot=breadth_snapshot))

    # P1-A: FII/DII flow features (market-level, same for all stocks on date)
    if not stock_df.empty:
        as_of = stock_df["date"].iloc[-1]
        features.update(compute_fii_dii_features(as_of, fii_dii_cache))

    # P2-A: Sector peer-mean propagation features
    if peer_mean_snapshot is not None and symbol in peer_mean_snapshot:
        features.update(peer_mean_snapshot[symbol])
    else:
        features.setdefault("peer_mean_momentum_10d", None)
        features.setdefault("peer_mean_rsi_14",       None)
        features.setdefault("peer_mean_vol_21d",      None)

    return features


# ══════════════════════════════════════════════════════════════
# INTERNAL: full generation loop
# ══════════════════════════════════════════════════════════════
def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by date, coerce the date column to plain python date objects, and
    numeric-coerce OHLCV columns — all ONCE per symbol, so every downstream
    per-date slice is a cheap read-only .iloc[] view (safe: no mutation
    happens on slices anymore, see _coerce_numeric) found via binary search
    instead of a per-row .apply(lambda ...) conversion + fresh copy."""
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) and isinstance(df["date"].iloc[0], pd.Timestamp):
        df = df.assign(date=pd.to_datetime(df["date"], errors="coerce").date)
        if df["date"].isna().any():
            raise ValueError("Corrupt date values found — NaT after coercion")
    return _coerce_numeric(df)


def _compute_peer_mean_snapshot(
    feat_date,
    sector_map: dict[str, str],
    slice_universe: dict[str, pd.DataFrame],
    price_features_cache: dict[str, dict],
) -> dict[str, dict]:
    """
    P2-A: Compute sector peer-mean features for all symbols on feat_date.
    For each symbol, take up to 10 same-sector peers and average their
    momentum_10d, rsi_14, and rolling_vol_21d computed earlier today.

    Uses price_features_cache {symbol: {feature: val}} already computed
    this date so we don't re-run full feature computation.
    Returns {symbol: {"peer_mean_momentum_10d": v, "peer_mean_rsi_14": v, "peer_mean_vol_21d": v}}
    """
    import numpy as np

    # Build sector peer groups from today's active symbols
    sector_to_symbols: dict[str, list[str]] = {}
    for sym, sec in sector_map.items():
        if sym in price_features_cache:
            sector_to_symbols.setdefault(sec or "Unknown", []).append(sym)

    result: dict[str, dict] = {}
    for sym in price_features_cache:
        own_sector = sector_map.get(sym, "Unknown")
        peers = [s for s in sector_to_symbols.get(own_sector, []) if s != sym]

        peer_momentum = [
            price_features_cache[p].get("momentum_10d")
            for p in peers[:10]
            if price_features_cache[p].get("momentum_10d") is not None
        ]
        peer_rsi = [
            price_features_cache[p].get("rsi_14")
            for p in peers[:10]
            if price_features_cache[p].get("rsi_14") is not None
        ]
        peer_vol = [
            price_features_cache[p].get("rolling_vol_21d")
            for p in peers[:10]
            if price_features_cache[p].get("rolling_vol_21d") is not None
        ]

        result[sym] = {
            "peer_mean_momentum_10d": round(float(np.mean(peer_momentum)), 4) if peer_momentum else None,
            "peer_mean_rsi_14":       round(float(np.mean(peer_rsi)),      4) if peer_rsi      else None,
            "peer_mean_vol_21d":      round(float(np.mean(peer_vol)),      4) if peer_vol      else None,
        }

    return result


def _generate_all(
    db: Session,
    universe_dfs: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame,
    sector_map: dict[str, str],
    version: int,
    only_symbols: Optional[set] = None,
) -> dict:
    """
    Compute features for every date in every symbol's history.
    For each date d, slices all DataFrames up to d so features are
    computed with only the information available on that day — IDENTICAL
    point-in-time semantics to the original implementation, just found via
    binary search on pre-sorted date arrays instead of a full-frame
    .apply(lambda ...) boolean mask, and looped date-major so the universe-
    wide slice used by market_features.py's breadth/sector calculations is
    built ONCE per date and reused across all symbols on that date, instead
    of being rebuilt from scratch inside every symbol's per-date iteration
    (this was the O(dates × symbols²) hot spot).
    """
    import numpy as np

    total_rows   = 0
    symbols_done = 0
    errors       = []

    # P1-A: Load FII/DII cache once for the whole run
    fii_cache = load_fii_dii_cache()
    if fii_cache is None:
        log.info("FII/DII cache empty — fii_* features will be None for this run")

    # Normalize once — avoids repeated Timestamp→date coercion in every slice
    universe_dfs = {s: _normalize_dates(df) for s, df in universe_dfs.items()}
    nifty_df     = _normalize_dates(nifty_df)

    # Pre-extract numpy date arrays for O(log n) searchsorted slicing
    universe_date_arr = {s: df["date"].values for s, df in universe_dfs.items()}
    nifty_date_arr    = nifty_df["date"].values if not nifty_df.empty else None

    # Precompute each symbol's FULL-HISTORY EMA50/200 series ONCE (vectorized
    # pandas .ewm(), O(n) per symbol) instead of recomputing ewm(...).mean()
    # from scratch for every symbol on every single date inside
    # market_features.compute_market_features's breadth loop — that
    # recomputation was ~45% of total backfill runtime (profiled). EMA is a
    # recursive expanding-window stat: its value at date T is unaffected by
    # dates after T, so this is exactly equivalent, just computed once.
    ema50_arr:  dict[str, "np.ndarray"] = {}
    ema200_arr: dict[str, "np.ndarray"] = {}
    close_arr:  dict[str, "np.ndarray"] = {}
    for s, df in universe_dfs.items():
        if df.empty:
            continue
        c = df["close"].astype(float)
        close_arr[s] = c.values
        if len(c) >= 50:
            ema50_arr[s] = c.ewm(span=50, adjust=False).mean().values
        if len(c) >= 200:
            ema200_arr[s] = c.ewm(span=200, adjust=False).mean().values

    # Collect all unique dates across the universe (sorted ascending)
    all_dates: list = sorted(set(
        d for arr in universe_date_arr.values() for d in arr
    ))

    target_symbols = [s for s in universe_dfs if only_symbols is None or s in only_symbols]
    sym_rows_count  = {s: 0 for s in target_symbols}
    sym_error_count = {s: 0 for s in target_symbols}
    # Track which symbols actually have a price on the current date, so we
    # skip computing/saving a vector for symbols with no bar that day.
    has_date_today: dict[str, bool] = {}

    for feat_date in all_dates:
        # Build the point-in-time slice ONCE for this date — shared by every
        # symbol's market_features() call below (this is the fix: was
        # rebuilt per (symbol, date) pair, i.e. once per symbol per date).
        slice_universe: dict[str, pd.DataFrame] = {}
        # O(1)-lookup breadth snapshot for this date — see EMA precompute above.
        breadth_snapshot: dict[str, tuple] = {}
        for s, arr in universe_date_arr.items():
            idx = int(np.searchsorted(arr, feat_date, side="right"))
            if idx > 0:
                slice_universe[s] = universe_dfs[s].iloc[:idx]
                curr = float(close_arr[s][idx - 1])
                ema50  = float(ema50_arr[s][idx - 1])  if s in ema50_arr  and idx >= 50  else None
                ema200 = float(ema200_arr[s][idx - 1]) if s in ema200_arr and idx >= 200 else None
                breadth_snapshot[s] = (curr, ema50, ema200)
            has_date_today[s] = idx > 0 and arr[idx - 1] == feat_date

        if nifty_date_arr is not None:
            n_idx = int(np.searchsorted(nifty_date_arr, feat_date, side="right"))
            slice_nifty = nifty_df.iloc[:n_idx] if n_idx > 0 else nifty_df.iloc[:0]
        else:
            slice_nifty = nifty_df

        # P2-A: First pass — compute price+trend features for all symbols on this date
        # so peer-mean snapshot can be built from them (O(n) not O(n^2)).
        base_features_cache: dict[str, dict] = {}
        for symbol in target_symbols:
            if not has_date_today.get(symbol):
                continue
            slice_stock = slice_universe.get(symbol)
            if slice_stock is None or len(slice_stock) < MIN_HISTORY_ROWS:
                continue
            try:
                from features.price_features  import compute_price_features
                from features.trend_features  import compute_trend_features
                from features.volatility_features import compute_volatility_features
                base = {}
                base.update(compute_price_features(slice_stock, slice_nifty))
                base.update(compute_trend_features(slice_stock))
                base.update(compute_volatility_features(slice_stock, slice_nifty))
                base_features_cache[symbol] = base
            except Exception:
                pass

        # Build peer-mean snapshot from base features
        peer_mean_snapshot = _compute_peer_mean_snapshot(
            feat_date, sector_map, slice_universe, base_features_cache
        )

        for symbol in target_symbols:
            if not has_date_today.get(symbol):
                continue
            slice_stock = slice_universe.get(symbol)
            if slice_stock is None or len(slice_stock) < MIN_HISTORY_ROWS:
                continue
            try:
                sp = db.begin_nested()
                try:
                    features = _compute_all_features(
                        symbol, slice_stock, slice_nifty,
                        slice_universe, sector_map,
                        breadth_snapshot=breadth_snapshot,
                        fii_dii_cache=fii_cache,
                        peer_mean_snapshot=peer_mean_snapshot,
                    )
                    # commit=False: one commit per DATE (below) covers all symbols
                    # processed on that date, instead of one commit per symbol —
                    # cuts commit count from ~435k to ~1236 for a full backfill.
                    rows = save_feature_vector(db, symbol, feat_date, features, version, commit=False)
                    sp.commit()
                except Exception:
                    sp.rollback()
                    raise
                sym_rows_count[symbol] += rows
            except Exception as exc:
                log.debug("%s %s: %s", symbol, feat_date, exc)
                sym_error_count[symbol] += 1

        db.commit()

    for symbol in target_symbols:
        if sym_error_count[symbol] == 0:
            symbols_done += 1
        else:
            errors.append(symbol)
        total_rows += sym_rows_count[symbol]
        log.info("%s: %d feature rows written.", symbol, sym_rows_count[symbol])

    return {
        "symbols_processed": symbols_done,
        "total_rows_written": total_rows,
        "errors": errors,
        "status": "COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
    }


# ══════════════════════════════════════════════════════════════
# INTERNAL: incremental generation loop
# ══════════════════════════════════════════════════════════════
def _generate_incremental(
    db: Session,
    universe_dfs: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame,
    sector_map: dict[str, str],
    version: int,
) -> dict:
    total_rows   = 0
    symbols_done = 0
    skipped      = 0
    errors       = []

    # P1-A: load FII cache once
    fii_cache = load_fii_dii_cache()

    # Normalize once (sort, coerce dates, coerce numerics) — same contract as
    # _generate_all; _compute_all_features no longer coerces its inputs.
    universe_dfs = {s: _normalize_dates(df) for s, df in universe_dfs.items()}
    nifty_df     = _normalize_dates(nifty_df)
    universe_date_arr = {s: df["date"].values for s, df in universe_dfs.items()}
    nifty_date_arr    = nifty_df["date"].values if not nifty_df.empty else None

    import numpy as np

    for symbol, stock_df in universe_dfs.items():
        if len(stock_df) < MIN_HISTORY_ROWS:
            continue
        try:
            last_computed = get_last_computed_date(db, symbol, version)
            latest_price  = stock_df["date"].iloc[-1]

            if last_computed is not None and last_computed >= latest_price:
                skipped += 1
                continue

            # Slice all data up to latest_price — same as _generate_all does per date.
            # This prevents look-ahead bias: incremental must use identical slicing.
            s_idx = int(np.searchsorted(universe_date_arr[symbol], latest_price, side="right"))
            slice_stock = stock_df.iloc[:s_idx]

            if nifty_date_arr is not None:
                n_idx = int(np.searchsorted(nifty_date_arr, latest_price, side="right"))
                slice_nifty = nifty_df.iloc[:n_idx]
            else:
                slice_nifty = nifty_df

            slice_universe = {}
            for s, arr in universe_date_arr.items():
                idx = int(np.searchsorted(arr, latest_price, side="right"))
                if idx > 0:
                    slice_universe[s] = universe_dfs[s].iloc[:idx]

            if len(slice_stock) < MIN_HISTORY_ROWS:
                skipped += 1
                continue

            features = _compute_all_features(symbol, slice_stock, slice_nifty,
                                             slice_universe, sector_map,
                                             fii_dii_cache=fii_cache)
            rows = save_feature_vector(db, symbol, latest_price, features, version, commit=False)
            total_rows += rows
            symbols_done += 1
        except Exception as exc:
            db.rollback()
            log.error("%s: incremental generation failed: %s", symbol, exc)
            errors.append(symbol)

    log.info("Incremental generation: processed=%d skipped=%d rows=%d errors=%d",
             symbols_done, skipped, total_rows, len(errors))
    return {
        "symbols_processed": symbols_done,
        "symbols_skipped":   skipped,
        "total_rows_written": total_rows,
        "errors": errors,
        "status": "COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
    }

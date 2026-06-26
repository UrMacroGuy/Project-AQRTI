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
from features.feature_store       import save_feature_vector, get_last_computed_date
from features.feature_registry    import seed_feature_metadata

log = get_logger("feature_generator")

# Minimum rows of price history required before generating features
MIN_HISTORY_ROWS = 30


# ══════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINTS
# ══════════════════════════════════════════════════════════════
def run_full_feature_generation(version: int = 1) -> dict:
    """
    Compute features for every symbol in the universe for every date that
    has price data but no stored features yet.
    Returns summary report.
    """
    log.info("=== FULL FEATURE GENERATION STARTED ===")
    with get_db() as db:
        seed_feature_metadata(db)
        universe_dfs, nifty_df, sector_map = _load_universe_data(db)
        report = _generate_all(db, universe_dfs, nifty_df, sector_map, version=version)
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
        stock_df = universe_dfs[symbol]
        return _compute_all_features(symbol, stock_df, nifty_df, universe_dfs, sector_map)


# ══════════════════════════════════════════════════════════════
# INTERNAL: data loading
# ══════════════════════════════════════════════════════════════
def _load_universe_data(
    db: Session,
    days: int = 1200,
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
            universe_dfs[stock.symbol] = pd.DataFrame([
                {
                    "date":            r.date,
                    "open":            r.open,
                    "high":            r.high,
                    "low":             r.low,
                    "close":           r.close,
                    "volume":          r.volume,
                    "delivery_volume": r.delivery_volume,
                    "daily_return":    r.daily_return,
                }
                for r in rows
            ])

    # Load NIFTY50
    nifty_rows = (
        db.query(IndexData)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff)
        .order_by(IndexData.date.asc())
        .all()
    )
    nifty_df = pd.DataFrame([
        {"date": r.date, "close": r.close, "returns": r.returns}
        for r in nifty_rows
    ]) if nifty_rows else pd.DataFrame()

    log.info("Loaded %d symbols, %d NIFTY rows.", len(universe_dfs), len(nifty_df))
    return universe_dfs, nifty_df, sector_map


# ══════════════════════════════════════════════════════════════
# INTERNAL: per-symbol feature computation
# ══════════════════════════════════════════════════════════════
def _compute_all_features(
    symbol: str,
    stock_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    universe_dfs: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
) -> dict[str, Optional[float]]:
    """Merge all feature category outputs into one flat dict."""
    features: dict[str, Optional[float]] = {}

    features.update(compute_price_features(stock_df, nifty_df))
    features.update(compute_volume_features(stock_df))
    features.update(compute_volatility_features(stock_df, nifty_df))
    features.update(compute_trend_features(stock_df))
    features.update(compute_market_features(symbol, stock_df, nifty_df, universe_dfs, sector_map))

    return features


# ══════════════════════════════════════════════════════════════
# INTERNAL: full generation loop
# ══════════════════════════════════════════════════════════════
def _generate_all(
    db: Session,
    universe_dfs: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame,
    sector_map: dict[str, str],
    version: int,
) -> dict:
    """
    Compute features for every date in every symbol's history.
    For each date d, slices all DataFrames up to d so features are
    computed with only the information available on that day.
    """
    total_rows   = 0
    symbols_done = 0
    errors       = []

    # Collect all unique dates across the universe (sorted ascending)
    all_dates: list = sorted(set(
        (d.date() if isinstance(d, pd.Timestamp) else d)
        for df in universe_dfs.values()
        for d in df["date"]
    ))

    # Nifty date index for fast slicing
    if not nifty_df.empty:
        nifty_dates = [
            (d.date() if isinstance(d, pd.Timestamp) else d)
            for d in nifty_df["date"]
        ]
    else:
        nifty_dates = []

    for symbol, stock_df in universe_dfs.items():
        sym_errors = 0
        sym_rows   = 0

        stock_dates = [
            (d.date() if isinstance(d, pd.Timestamp) else d)
            for d in stock_df["date"]
        ]

        for feat_date in all_dates:
            # Only compute for dates where this symbol has a price
            if feat_date not in stock_dates:
                continue

            # Slice all data up to and including feat_date
            slice_stock = stock_df[
                stock_df["date"].apply(
                    lambda d: (d.date() if isinstance(d, pd.Timestamp) else d) <= feat_date
                )
            ].copy()

            if len(slice_stock) < MIN_HISTORY_ROWS:
                continue

            slice_nifty = nifty_df[
                nifty_df["date"].apply(
                    lambda d: (d.date() if isinstance(d, pd.Timestamp) else d) <= feat_date
                )
            ].copy() if not nifty_df.empty else nifty_df

            slice_universe = {
                s: df[
                    df["date"].apply(
                        lambda d: (d.date() if isinstance(d, pd.Timestamp) else d) <= feat_date
                    )
                ]
                for s, df in universe_dfs.items()
            }

            try:
                features = _compute_all_features(symbol, slice_stock, slice_nifty,
                                                 slice_universe, sector_map)
                rows = save_feature_vector(db, symbol, feat_date, features, version)
                sym_rows += rows
            except Exception as exc:
                log.debug("%s %s: %s", symbol, feat_date, exc)
                sym_errors += 1

        if sym_errors == 0:
            symbols_done += 1
        else:
            errors.append(symbol)
        total_rows += sym_rows
        db.commit()
        log.info("%s: %d feature rows written.", symbol, sym_rows)

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

    for symbol, stock_df in universe_dfs.items():
        if len(stock_df) < MIN_HISTORY_ROWS:
            continue
        try:
            last_computed = get_last_computed_date(db, symbol, version)
            latest_price  = stock_df["date"].iloc[-1]
            if isinstance(latest_price, pd.Timestamp):
                latest_price = latest_price.date()

            if last_computed is not None and last_computed >= latest_price:
                skipped += 1
                continue

            # Slice all data up to latest_price — same as _generate_all does per date.
            # This prevents look-ahead bias: incremental must use identical slicing.
            def _to_date(d):
                return d.date() if isinstance(d, pd.Timestamp) else d

            slice_stock = stock_df[
                stock_df["date"].apply(_to_date) <= latest_price
            ].copy()
            slice_nifty = nifty_df[
                nifty_df["date"].apply(_to_date) <= latest_price
            ].copy() if not nifty_df.empty else nifty_df
            slice_universe = {
                s: df[df["date"].apply(_to_date) <= latest_price]
                for s, df in universe_dfs.items()
            }

            if len(slice_stock) < MIN_HISTORY_ROWS:
                skipped += 1
                continue

            features = _compute_all_features(symbol, slice_stock, slice_nifty,
                                             slice_universe, sector_map)
            rows = save_feature_vector(db, symbol, latest_price, features, version)
            total_rows += rows
            symbols_done += 1
            log.debug("%s: %d features written for %s.", symbol, rows, latest_price)
        except Exception as exc:
            log.error("%s: incremental generation failed: %s", symbol, exc)
            errors.append(symbol)

    return {
        "symbols_processed": symbols_done,
        "symbols_skipped":   skipped,
        "total_rows_written": total_rows,
        "errors": errors,
        "status": "COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
    }

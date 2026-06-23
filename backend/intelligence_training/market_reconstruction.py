"""
AQRTI Market Reconstruction Engine — Phase 8.5A
Reconstructs a full feature matrix for any historical date range,
with strict no-future-leakage: only data up to reconstruction_date is used.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("market_reconstruction")

LOOKBACK_WINDOWS = {
    "price_30d": 30,
    "price_90d": 90,
    "feature_latest": 1,
    "news_7d": 7,
    "sentiment_3d": 3,
}


def reconstruct_feature_matrix(
    reconstruction_date: date,
    symbols: Optional[List[str]] = None,
    db: Optional[Session] = None,
) -> pd.DataFrame:
    """
    Build the feature matrix exactly as it would have existed on reconstruction_date.
    Every value is from data that was available at close of reconstruction_date.
    Returns DataFrame with columns: symbol, date, <feature columns...>
    """
    own_session = db is None
    if own_session:
        db = get_session_factory()()

    try:
        symbol_filter = ""
        params: Dict[str, Any] = {"d": reconstruction_date}
        if symbols:
            placeholders = ",".join(f":s{i}" for i in range(len(symbols)))
            symbol_filter = f" AND symbol IN ({placeholders})"
            for i, s in enumerate(symbols):
                params[f"s{i}"] = s

        rows = db.execute(
            f"SELECT symbol, feature_name, value FROM feature_values "
            f"WHERE date = :d{symbol_filter}",
            params,
        ).fetchall()

        if not rows:
            logger.warning("No features found for reconstruction date %s", reconstruction_date)
            return pd.DataFrame()

        # Pivot to wide format
        records: Dict[str, Dict[str, float]] = {}
        for r in rows:
            if r.symbol not in records:
                records[r.symbol] = {"symbol": r.symbol, "date": reconstruction_date}
            records[r.symbol][r.feature_name] = r.value

        df = pd.DataFrame(list(records.values()))
        logger.info("Reconstructed feature matrix for %s: %d symbols, %d features",
                    reconstruction_date, len(df), len(df.columns) - 2)
        return df

    finally:
        if own_session:
            db.close()


def reconstruct_price_series(
    symbol: str,
    as_of_date: date,
    lookback_days: int = 252,
    db: Optional[Session] = None,
) -> pd.DataFrame:
    """
    Reconstruct the price series for a symbol up to as_of_date.
    Guaranteed: no rows beyond as_of_date are included.
    """
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        start = as_of_date - timedelta(days=lookback_days)
        rows = db.execute(
            "SELECT date, open, high, low, close, volume, daily_return "
            "FROM daily_prices WHERE symbol = :sym AND date BETWEEN :s AND :d ORDER BY date",
            {"sym": symbol, "s": start, "d": as_of_date},
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r._mapping) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df
    finally:
        if own_session:
            db.close()


def reconstruct_regime_history(
    as_of_date: date,
    lookback_days: int = 252,
    db: Optional[Session] = None,
) -> pd.DataFrame:
    """Regime sequence up to as_of_date."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        start = as_of_date - timedelta(days=lookback_days)
        rows = db.execute(
            "SELECT date, regime, confidence, breadth_pct, volatility_pct "
            "FROM market_regimes WHERE date BETWEEN :s AND :d ORDER BY date",
            {"s": start, "d": as_of_date},
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r._mapping) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")
    finally:
        if own_session:
            db.close()


def reconstruct_sentiment_series(
    entity: str,
    as_of_date: date,
    lookback_days: int = 90,
    db: Optional[Session] = None,
) -> pd.DataFrame:
    """Sentiment score series for an entity up to as_of_date."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        start = as_of_date - timedelta(days=lookback_days)
        rows = db.execute(
            "SELECT date(timestamp) as dt, score, velocity, confidence "
            "FROM sentiment_records WHERE entity = :e AND date(timestamp) BETWEEN :s AND :d ORDER BY dt",
            {"e": entity, "s": start, "d": as_of_date},
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([dict(r._mapping) for r in rows])
        df["dt"] = pd.to_datetime(df["dt"])
        return df.set_index("dt")
    finally:
        if own_session:
            db.close()


def get_trading_dates(
    start_date: date,
    end_date: date,
    db: Optional[Session] = None,
) -> List[date]:
    """Return all dates in [start_date, end_date] that have price data."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            "SELECT DISTINCT date FROM daily_prices WHERE date BETWEEN :s AND :e ORDER BY date",
            {"s": start_date, "e": end_date},
        ).fetchall()
        result = []
        for r in rows:
            d = r[0]
            if isinstance(d, str):
                d = date.fromisoformat(d)
            result.append(d)
        return result
    finally:
        if own_session:
            db.close()


def reconstruct_full_context(
    as_of_date: date,
    symbol: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Single-call reconstruction of all context for (symbol, date):
    features, price series, regime, sentiment, options.
    Used by the time machine for training sample generation.
    """
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        context: Dict[str, Any] = {
            "symbol": symbol,
            "date": as_of_date.isoformat(),
        }

        # Features
        feat_rows = db.execute(
            "SELECT feature_name, value FROM feature_values WHERE symbol = :s AND date = :d",
            {"s": symbol, "d": as_of_date},
        ).fetchall()
        context["features"] = {r.feature_name: r.value for r in feat_rows}

        # Recent price stats (5d, 10d)
        price_rows = db.execute(
            "SELECT date, close, daily_return FROM daily_prices "
            "WHERE symbol = :s AND date <= :d ORDER BY date DESC LIMIT 30",
            {"s": symbol, "d": as_of_date},
        ).fetchall()
        if price_rows:
            context["recent_close"] = price_rows[0].close
            returns = [r.daily_return for r in price_rows if r.daily_return is not None]
            context["return_5d_realized"] = sum(returns[:5]) if len(returns) >= 5 else None
            context["return_10d_realized"] = sum(returns[:10]) if len(returns) >= 10 else None

        # Regime
        regime_row = db.execute(
            "SELECT regime, confidence FROM market_regimes WHERE date <= :d ORDER BY date DESC LIMIT 1",
            {"d": as_of_date},
        ).fetchone()
        if regime_row:
            context["regime"] = regime_row.regime
            context["regime_confidence"] = regime_row.confidence

        # Sentiment
        sent_row = db.execute(
            "SELECT score, velocity FROM sentiment_records "
            "WHERE entity = :e AND date(timestamp) <= :d ORDER BY timestamp DESC LIMIT 1",
            {"e": symbol, "d": as_of_date},
        ).fetchone()
        if sent_row:
            context["sentiment_score"] = sent_row.score
            context["sentiment_velocity"] = sent_row.velocity

        # AQRTI confidence on this date
        pred_row = db.execute(
            "SELECT confidence, direction FROM predictions WHERE symbol = :s AND date = :d",
            {"s": symbol, "d": as_of_date},
        ).fetchone()
        if pred_row:
            context["aqrti_confidence"] = pred_row.confidence
            context["aqrti_direction"] = pred_row.direction

        return context
    finally:
        if own_session:
            db.close()

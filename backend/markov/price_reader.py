"""
Read-only access to existing OHLCV data (daily_prices, index_data tables)
for the Markov module. Plain SQL via the shared engine — deliberately does
NOT import aqrti.database.models, so this module has zero coupling to the
main ORM schema beyond the raw table/column names below.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from aqrti.database.engine import get_engine
from aqrti.utils.logger import get_logger

log = get_logger("markov.price_reader")


def _coerce_date_col(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite returns date columns as ISO strings via the raw driver — coerce
    to plain python date objects so downstream SQLAlchemy Date-typed writes
    (markov_* tables) don't reject them."""
    if "date" in df.columns and not df.empty:
        df = df.assign(date=pd.to_datetime(df["date"], errors="coerce").dt.date)
        df = df.dropna(subset=["date"])
    return df


def load_index_prices(index_name: str = "NIFTY50", years: int = 10) -> pd.DataFrame:
    """Returns DataFrame[date, close, returns] sorted ascending, or empty if no data."""
    cutoff = date.today() - timedelta(days=int(years * 365.25))
    sql = text("""
        SELECT date, close, returns
        FROM index_data
        WHERE index_name = :idx AND date >= :cutoff
        ORDER BY date ASC
    """)
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"idx": index_name, "cutoff": cutoff}).fetchall()
    except Exception:
        log.exception("Failed reading index_data for %s", index_name)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "close", "returns"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["returns"] = pd.to_numeric(df["returns"], errors="coerce")
    df = _coerce_date_col(df)
    return df.dropna(subset=["close"]).reset_index(drop=True)


def load_symbol_prices(symbol: str, years: int = 10) -> pd.DataFrame:
    """Returns DataFrame[date, close] for a single equity symbol, sorted ascending."""
    cutoff = date.today() - timedelta(days=int(years * 365.25))
    sql = text("""
        SELECT date, close
        FROM daily_prices
        WHERE symbol = :sym AND date >= :cutoff
        ORDER BY date ASC
    """)
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"sym": symbol, "cutoff": cutoff}).fetchall()
    except Exception:
        log.exception("Failed reading daily_prices for %s", symbol)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = _coerce_date_col(df)
    return df.dropna(subset=["close"]).reset_index(drop=True)

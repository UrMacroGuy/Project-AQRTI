"""
Backfill 5yr synthetic index futures data (NIFTY50, BANKNIFTY, SENSEX,
NIFTYIT, NIFTYPHARMA).

DATA SOURCE CAVEAT: no free source carries real historical NSE index
futures contract prices. This script downloads the real underlying SPOT
index history (yfinance) and models the futures price as
F = S * e^((r-q)*T) — a standard cost-of-carry approximation, not real
contract ticks. Every row is written with is_synthetic=True. See
strategies/index_futures_config.py for the full rationale and the
risk-free-rate / dividend-yield constants used.

Builds a continuous monthly-contract series: for each calendar month,
the "current" contract's basis shrinks toward zero as it approaches its
last-Thursday expiry (the real futures-spot convergence at expiry), then
rolls to the next month.

Usage: python scripts/backfill_index_futures.py
"""
import sys, os
from datetime import date, timedelta
import calendar

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import yfinance as yf
import pandas as pd
import math

from aqrti.database.engine import get_session_factory
from aqrti.database.models import IndexFuturesContract, IndexFuturesPrice, IndexFuturesRoll
from strategies.index_futures_config import (
    INDEX_FUTURES_UNIVERSE, CONTRACT_SPECS, RISK_FREE_RATE, DIVIDEND_YIELD,
    BACKTEST_YEARS,
)


def _last_thursday(year: int, month: int) -> date:
    """Last Thursday of the given month — NSE F&O monthly expiry convention."""
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != 3:  # Thursday == 3
        d -= timedelta(days=1)
    return d


def _contract_month_and_expiry(d: date) -> tuple[str, date]:
    """Which contract month a given trading date belongs to, and its expiry.
    If d is past this month's expiry, it belongs to next month's contract."""
    expiry = _last_thursday(d.year, d.month)
    if d > expiry:
        nxt_month = d.month + 1
        nxt_year = d.year
        if nxt_month > 12:
            nxt_month = 1
            nxt_year += 1
        expiry = _last_thursday(nxt_year, nxt_month)
        return f"{nxt_year:04d}-{nxt_month:02d}", expiry
    return f"{d.year:04d}-{d.month:02d}", expiry


def _basis(spot: float, days_to_expiry: int) -> float:
    """F - S under cost-of-carry: F = S * e^((r-q)*T)."""
    t = max(days_to_expiry, 0) / 365.0
    fwd = spot * math.exp((RISK_FREE_RATE - DIVIDEND_YIELD) * t)
    return fwd - spot


def ensure_contract_row(db, index_name: str) -> None:
    spec = CONTRACT_SPECS[index_name]
    existing = db.query(IndexFuturesContract).filter_by(index_name=index_name).first()
    if existing:
        return
    db.add(IndexFuturesContract(
        index_name=index_name,
        underlying_source=INDEX_FUTURES_UNIVERSE[index_name],
        exchange=spec["exchange"],
        lot_size=spec["lot_size"],
        tick_size=spec["tick_size"],
        margin_pct=0.13,
        active=True,
    ))
    db.commit()


def backfill_one_index(db, index_name: str) -> dict:
    ticker = INDEX_FUTURES_UNIVERSE[index_name]
    print(f"[{index_name}] downloading spot history for {ticker} ...", flush=True)

    start = date.today() - timedelta(days=BACKTEST_YEARS * 365 + 30)
    df = yf.download(ticker, start=str(start), end=str(date.today() + timedelta(days=1)),
                      progress=False, auto_adjust=True)
    if df.empty:
        print(f"[{index_name}] no data returned, skipping")
        return {"index_name": index_name, "rows": 0}

    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    rows_written = 0
    rolls_written = 0
    prev_contract_month = None

    for _, row in df.iterrows():
        d = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
        spot_close = float(row["Close"]) if pd.notna(row["Close"]) else None
        spot_open  = float(row["Open"])  if pd.notna(row["Open"])  else None
        spot_high  = float(row["High"])  if pd.notna(row["High"])  else None
        spot_low   = float(row["Low"])   if pd.notna(row["Low"])   else None
        if spot_close is None:
            continue

        contract_month, expiry = _contract_month_and_expiry(d)
        days_to_expiry = (expiry - d).days
        basis = _basis(spot_close, days_to_expiry)

        fut_close = spot_close + basis
        fut_open  = (spot_open  + basis) if spot_open  is not None else None
        fut_high  = (spot_high  + basis) if spot_high  is not None else None
        fut_low   = (spot_low   + basis) if spot_low   is not None else None

        existing = (
            db.query(IndexFuturesPrice)
            .filter_by(index_name=index_name, contract_month=contract_month, date=d)
            .first()
        )
        if not existing:
            db.add(IndexFuturesPrice(
                index_name=index_name,
                contract_month=contract_month,
                date=d,
                expiry_date=expiry,
                open=fut_open, high=fut_high, low=fut_low, close=fut_close,
                spot_close=spot_close,
                basis=round(basis, 4),
                is_synthetic=True,
            ))
            rows_written += 1

        if prev_contract_month is not None and contract_month != prev_contract_month:
            db.add(IndexFuturesRoll(
                index_name=index_name,
                roll_date=d,
                from_contract_month=prev_contract_month,
                to_contract_month=contract_month,
                from_close=fut_close,
                to_close=fut_close,
                roll_cost_pct=0.0,  # continuous series is basis-adjusted; no jump to record here
            ))
            rolls_written += 1
        prev_contract_month = contract_month

    db.commit()
    print(f"[{index_name}] wrote {rows_written} price rows, {rolls_written} roll markers")
    return {"index_name": index_name, "rows": rows_written, "rolls": rolls_written}


def main():
    db = get_session_factory()()
    summary = []
    for index_name in INDEX_FUTURES_UNIVERSE:
        ensure_contract_row(db, index_name)
        summary.append(backfill_one_index(db, index_name))
    db.close()

    print("\n=== Backfill summary ===")
    for s in summary:
        print(f"  {s['index_name']}: {s['rows']} rows")


if __name__ == "__main__":
    main()

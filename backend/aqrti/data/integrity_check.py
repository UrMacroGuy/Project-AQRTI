"""
Price Integrity Check — split/dividend adjustment drift detection + healing.

Problem: prices are ingested incrementally with yfinance auto_adjust=True.
When a stock splits or pays a dividend, yfinance re-adjusts the ENTIRE
history — but we only fetch new dates, so previously stored rows keep the
OLD adjustment basis. The stored series then has a discontinuity that
corrupts every derived feature and backtest.

Detection: re-download the last ~250 trading days for a symbol and compare
overlapping closes against stored rows. If >3 dates differ by >1%, the
stored history has drifted.

Healing: delete the symbol's price rows, full re-download (5y), delete its
feature rows, regenerate features for that symbol only.

Wire-up: weekly scheduler job (Saturday, off-market) + POST /admin/integrity-sweep.
"""

from __future__ import annotations

import sys, os, time
from datetime import date, timedelta
from io import StringIO
from contextlib import redirect_stderr
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db
from aqrti.database.models import DailyPrice, Stock, FeatureValue
from aqrti.utils.logger import get_logger

log = get_logger("integrity_check")

DRIFT_TOLERANCE_PCT   = 1.0   # % close mismatch that counts as drift
DRIFT_MIN_BAD_DATES   = 3     # this many mismatched dates → symbol is drifted
OVERLAP_DAYS          = 250   # trading days to compare
FULL_HISTORY_YEARS    = 5


def _symbol_to_ticker(symbol: str) -> str:
    """DB symbol → yfinance ticker (Indian symbols get .NS suffix)."""
    if "." in symbol:
        return symbol
    try:
        from strategies.strategy_backtester import _india_symbol_set
        if symbol in _india_symbol_set():
            return symbol + ".NS"
    except Exception:
        pass
    return symbol


def _download(ticker: str, start: date) -> pd.DataFrame:
    buf = StringIO()
    with redirect_stderr(buf):
        df = yf.download(
            ticker,
            start=str(start),
            end=str(date.today() + timedelta(days=1)),
            progress=False,
            auto_adjust=True,
        )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def check_symbol_adjustment(db: Session, symbol: str) -> dict:
    """
    Compare fresh adjusted closes against stored closes over the last
    OVERLAP_DAYS. Returns {symbol, checked, mismatches, drifted, detail}.
    """
    since = date.today() - timedelta(days=int(OVERLAP_DAYS * 1.6))
    stored = {
        r[0]: r[1] for r in
        db.query(DailyPrice.date, DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= since,
                DailyPrice.close.isnot(None))
        .all()
    }
    if len(stored) < 30:
        return {"symbol": symbol, "checked": 0, "mismatches": 0,
                "drifted": False, "detail": "insufficient stored history"}

    ticker = _symbol_to_ticker(symbol)
    fresh = _download(ticker, since)
    if fresh.empty:
        return {"symbol": symbol, "checked": 0, "mismatches": 0,
                "drifted": False, "detail": "download failed"}

    mismatches = []
    checked = 0
    for _, row in fresh.iterrows():
        try:
            d = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
            fresh_close = float(row["Close"])
        except Exception:
            continue
        if d not in stored or fresh_close <= 0:
            continue
        checked += 1
        diff_pct = abs(stored[d] - fresh_close) / fresh_close * 100
        if diff_pct > DRIFT_TOLERANCE_PCT:
            mismatches.append((str(d), round(stored[d], 2), round(fresh_close, 2), round(diff_pct, 2)))

    drifted = len(mismatches) >= DRIFT_MIN_BAD_DATES
    return {
        "symbol": symbol, "checked": checked, "mismatches": len(mismatches),
        "drifted": drifted,
        "detail": mismatches[:5] if drifted else "ok",
    }


def heal_symbol(db: Session, symbol: str, regen_features: bool = True) -> dict:
    """
    Full re-download of a drifted symbol: replace all price rows with a
    consistent freshly-adjusted history, then regenerate its features.
    """
    ticker = _symbol_to_ticker(symbol)
    start = date.today() - timedelta(days=FULL_HISTORY_YEARS * 365)
    fresh = _download(ticker, start)
    if fresh.empty:
        return {"symbol": symbol, "healed": False, "error": "download failed"}

    fresh = fresh.sort_values("Date")
    fresh["daily_return"] = fresh["Close"].pct_change(fill_method=None) * 100

    deleted = db.query(DailyPrice).filter(DailyPrice.symbol == symbol).delete()
    inserted = 0
    for _, row in fresh.iterrows():
        try:
            close_val = float(row["Close"])
            if pd.isna(close_val) or close_val <= 0:
                continue
            d = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
            def _f(v):
                try:
                    f = float(v)
                    return None if pd.isna(f) else round(f, 4)
                except (TypeError, ValueError):
                    return None
            db.add(DailyPrice(
                symbol=symbol, date=d,
                open=_f(row.get("Open")), high=_f(row.get("High")),
                low=_f(row.get("Low")), close=round(close_val, 4),
                adj_close=round(close_val, 4),
                volume=_f(row.get("Volume")),
                daily_return=_f(row.get("daily_return")),
            ))
            inserted += 1
        except Exception:
            continue
    db.commit()

    feat_deleted = 0
    if regen_features:
        feat_deleted = db.query(FeatureValue).filter(FeatureValue.symbol == symbol).delete()
        db.commit()

    log.info("Healed %s: deleted %d price rows, inserted %d, dropped %d feature rows",
             symbol, deleted, inserted, feat_deleted)
    return {"symbol": symbol, "healed": True, "price_rows": inserted,
            "feature_rows_dropped": feat_deleted}


def run_integrity_sweep(batch_size: int = 50, max_heals: int = 20) -> dict:
    """
    Check every active symbol with price data for adjustment drift; heal
    drifted symbols (up to max_heals per run to bound yfinance load), then
    regenerate features for healed symbols in one pass.
    """
    log.info("=== PRICE INTEGRITY SWEEP STARTED ===")
    report = {"checked": 0, "drifted": [], "healed": [], "errors": []}

    with get_db() as db:
        symbols = [
            r[0] for r in
            db.query(DailyPrice.symbol)
            .filter(DailyPrice.symbol.in_(
                db.query(Stock.symbol).filter(Stock.active == True).scalar_subquery()
            ))
            .group_by(DailyPrice.symbol)
            .all()
        ]

    healed_symbols: list[str] = []
    for i, sym in enumerate(symbols):
        try:
            with get_db() as db:
                chk = check_symbol_adjustment(db, sym)
                report["checked"] += 1
                if chk["drifted"]:
                    report["drifted"].append(sym)
                    log.warning("Drift detected %s: %s", sym, chk["detail"])
                    if len(healed_symbols) < max_heals:
                        heal = heal_symbol(db, sym)
                        if heal.get("healed"):
                            healed_symbols.append(sym)
                            report["healed"].append(sym)
        except Exception as exc:
            report["errors"].append(f"{sym}: {exc}")
        # Rate-limit yfinance
        if (i + 1) % batch_size == 0:
            time.sleep(2)

    # Regenerate features for healed symbols in one pass
    if healed_symbols:
        try:
            from features.feature_generator import run_full_feature_generation
            regen = run_full_feature_generation(only_symbols=set(healed_symbols))
            report["feature_regen"] = regen
        except Exception as exc:
            report["errors"].append(f"feature_regen: {exc}")

    log.info("=== INTEGRITY SWEEP COMPLETE: checked=%d drifted=%d healed=%d ===",
             report["checked"], len(report["drifted"]), len(report["healed"]))
    return report

"""
Index Futures Feature Generation
Computes features for index instruments (NIFTY50, BANKNIFTY, etc.) using
their own synthetic continuous futures close series.

Reuses compute_price_features / compute_trend_features / compute_volatility_features
UNCHANGED — all three operate purely on OHLC and have no volume/delivery
dependency, so they apply to an index future exactly as they do to a stock.
Volume-, delivery-, and liquidity-based features (volume_features.py,
delivery_ratio, etc.) are deliberately NOT computed here — index futures
"volume" data (open interest aside) isn't a comparable traded-liquidity
signal the way stock volume is, and none of the stock volume features
translate meaningfully.

Futures-specific features (basis_pct) are computed separately from the
spot_close and basis columns in IndexFuturesPrice — these capture the
cost-of-carry signal that has no equivalent in the equity pipeline.

Cross-index relative strength (e.g. BANKNIFTY vs NIFTY50) is intentionally
out of scope for v1 — each index's features are computed standalone. This
can be added later the same way stock-vs-NIFTY relative strength works,
once there's a reason to test sector-index-vs-benchmark strategies.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import func

from aqrti.database.engine import get_session_factory
from aqrti.database.models import IndexFuturesPrice, IndexFuturesFeatureValue
from aqrti.utils.logger import get_logger
from features.price_features import compute_price_features
from features.trend_features import compute_trend_features
from features.volatility_features import compute_volatility_features

log = get_logger("index_features")

VERSION = 1


def _load_continuous_series(db, index_name: str) -> pd.DataFrame:
    """
    Load the continuous futures OHLC + spot_close + basis series for one
    index, sorted ascending.  One row per date (the "current" contract for
    that date — see backfill_index_futures.py's contract-month rollover
    logic).  spot_close and basis are needed for futures-specific features
    (basis_pct) that have no stock equivalent.
    """
    rows = (
        db.query(IndexFuturesPrice.date, IndexFuturesPrice.open,
                 IndexFuturesPrice.high, IndexFuturesPrice.low,
                 IndexFuturesPrice.close,
                 IndexFuturesPrice.spot_close, IndexFuturesPrice.basis)
        .filter(IndexFuturesPrice.index_name == index_name)
        .order_by(IndexFuturesPrice.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close",
                                     "spot_close", "basis"])
    for col in ("open", "high", "low", "close", "spot_close", "basis"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _save_feature_vector(db, index_name: str, on_date, features: dict) -> int:
    """Bulk upsert — same on_conflict_do_update pattern as feature_store.py."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    rows = [
        {
            "index_name": index_name,
            "date": on_date,
            "feature_name": name,
            "value": val,
            "version": VERSION,
        }
        for name, val in features.items()
        if val is not None
    ]
    if not rows:
        return 0

    stmt = sqlite_insert(IndexFuturesFeatureValue).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["index_name", "date", "feature_name", "version"],
        set_={"value": stmt.excluded.value},
    )
    db.execute(stmt)
    return len(rows)


def compute_futures_features(df: pd.DataFrame) -> dict:
    """
    Futures-specific features that have no stock equivalent.
    Input: DataFrame with columns [close, spot_close, basis] sorted by date.
    Returns dict of {feature_name: float|None} for the last row.
    """
    if df.empty or len(df) < 2:
        return {}
    last = df.iloc[-1]
    sp = last.get("spot_close")
    bs = last.get("basis")
    results = {}
    if sp is not None and sp > 0 and bs is not None:
        results["basis_pct"] = round(bs / sp * 100, 4)
    else:
        results["basis_pct"] = None
    return results


def run_index_feature_generation(index_names: list[str] | None = None) -> dict:
    """
    Full history feature generation for index futures. Walks each index's
    continuous series date-by-date (matching the date-major pattern used
    for stocks) computing price/trend/volatility features on the trailing
    window up to and including that date.
    """
    db = get_session_factory()()
    from strategies.index_futures_config import INDEX_FUTURES_UNIVERSE
    targets = index_names or list(INDEX_FUTURES_UNIVERSE.keys())

    summary = {}
    for index_name in targets:
        df = _load_continuous_series(db, index_name)
        if df.empty:
            log.warning("No price data for %s, skipping", index_name)
            summary[index_name] = 0
            continue

        rows_written = 0
        # Minimum history needed for the longest-window feature
        # (breakout_distance_52w needs 252 rows) — skip dates before that.
        min_rows = 252
        for i in range(min_rows, len(df)):
            window = df.iloc[: i + 1]
            on_date = window.iloc[-1]["date"]

            features = {}
            features.update(compute_price_features(window))
            features.update(compute_trend_features(window))
            features.update(compute_volatility_features(window))
            features.update(compute_futures_features(window))

            n = _save_feature_vector(db, index_name, on_date, features)
            rows_written += n

            if (i - min_rows) % 200 == 0:
                db.commit()

        db.commit()
        summary[index_name] = rows_written
        log.info("Index features: %s -> %d feature rows written", index_name, rows_written)

    db.close()
    return summary

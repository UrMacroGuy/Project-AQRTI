"""
One-off historical backfill for the two features added 2026-07-14:
return_126d and tom_window (see features/price_features.py for their
definitions and the strategy templates that consume them —
week52_high_momentum and turn_of_month in strategy_generator.py).

Newly registered features only start appearing in feature_values from the
next generation run forward; the backtester reads features from that table,
so without a historical backfill the new templates would fail-closed to
zero trades on all history. This computes REAL values from REAL price
history via the exact same compute_price_features() code path and
expanding point-in-time slices the daily generator uses — it is precisely
the subset of a full regeneration covering these two features, not
fabricated data.

Run with the backend STOPPED (SQLite lock contention).
Usage: python scripts/backfill_new_features.py
"""

from __future__ import annotations

import sys, os, time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import pandas as pd

from aqrti.database.engine import get_session_factory
from features.price_features import compute_price_features
from features.feature_store import save_feature_vector
from sqlalchemy import text

# 2026-07-14: return_126d + tom_window (both already backfilled).
# 2026-07-14c: trend_tstat_63d. save_feature_vector upserts, so re-running
# over an already-backfilled feature is idempotent, but pass only the
# features that actually need history to keep the run fast.
NEW_FEATURES = ["trend_tstat_63d"]


def main() -> None:
    Session = get_session_factory()
    db = Session()
    t0 = time.time()
    total_rows = 0
    try:
        symbols = [r[0] for r in db.execute(text(
            "SELECT symbol FROM stocks WHERE active = 1 ORDER BY symbol"))]
        print(f"Backfilling {NEW_FEATURES} for {len(symbols)} symbols...")

        for symbol in symbols:
            df = pd.read_sql(
                text("SELECT date, open, high, low, close, volume, daily_return "
                     "FROM daily_prices WHERE symbol = :s ORDER BY date"),
                db.bind, params={"s": symbol}, parse_dates=["date"],
            )
            if df.empty:
                print(f"  {symbol}: no price history, skipped")
                continue

            written = 0
            for i in range(len(df)):
                sl = df.iloc[: i + 1]
                feats = compute_price_features(sl)
                subset = {k: feats.get(k) for k in NEW_FEATURES if feats.get(k) is not None}
                if not subset:
                    continue
                feat_date = sl["date"].iloc[-1].date()
                written += save_feature_vector(db, symbol, feat_date, subset, commit=False)
            db.commit()
            total_rows += written
            print(f"  {symbol}: {written} feature rows written ({len(df)} dates)")
    finally:
        db.close()

    print(f"Done: {total_rows} rows in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

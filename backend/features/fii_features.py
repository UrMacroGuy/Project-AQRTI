"""
AQRTI FII/DII Flow Features
Computes 6 institutional flow features from the fii_dii_flows table.

Features are market-level (same value for all stocks on a given date) but
included in each stock's feature vector because institutional buying pressure
is one of the strongest predictors of near-term market direction in Indian markets.

If the fii_dii_flows table is empty, all features return None — honesty over
imputation. The UI will show "NO DATA" for those cells.

Point-in-time safe: all computations read rows with flow_date <= t.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np


def compute_fii_dii_features(
    as_of_date: date,
    fii_dii_cache: Optional["FIIDIICache"] = None,
) -> dict[str, Optional[float]]:
    """
    Return 6 FII/DII flow features as of `as_of_date`.
    Uses FIIDIICache if provided (pre-loaded for efficiency during batch generation);
    otherwise falls back to a direct DB query (single-symbol on-demand path).

    Features:
      fii_net_1d       - FII net buy/sell today (crores)
      fii_net_5d       - Rolling 5-day FII net (crores)
      fii_net_20d      - Rolling 20-day FII net (crores)
      dii_net_1d       - DII net buy/sell today (crores)
      fii_dii_ratio    - FII net / DII net (signed ratio, 0 when DII=0)
      institutional_flow_signal - encoded: BULLISH=1, BEARISH=-1, NEUTRAL=0
    """
    if fii_dii_cache is not None:
        return fii_dii_cache.get(as_of_date)

    # Single-symbol on-demand fallback — direct DB read
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import FIIDIIFlow

        with get_db() as db:
            rows = (
                db.query(FIIDIIFlow)
                .filter(
                    FIIDIIFlow.flow_date <= as_of_date,
                    FIIDIIFlow.segment.in_(["equity", "total", None]),
                )
                .order_by(FIIDIIFlow.flow_date.desc())
                .limit(60)
                .all()
            )
        cache = FIIDIICache(rows)
        return cache.get(as_of_date)
    except Exception:
        return _empty_features()


def _empty_features() -> dict[str, Optional[float]]:
    return {
        "fii_net_1d":                None,
        "fii_net_5d":                None,
        "fii_net_20d":               None,
        "dii_net_1d":                None,
        "fii_dii_ratio":             None,
        "institutional_flow_signal": None,
    }


class FIIDIICache:
    """
    Pre-loaded in-memory cache of FII/DII flows for efficient batch generation.
    Load once per feature generation run, query per date.
    """

    def __init__(self, rows: list) -> None:
        # Build {date: {category: row}} lookup
        from collections import defaultdict
        self._by_date: dict[date, dict[str, object]] = defaultdict(dict)
        self._sorted_dates: list[date] = []

        for row in rows:
            cat = (row.category or "").upper()
            if cat in ("FII", "DII"):
                self._by_date[row.flow_date][cat] = row

        self._sorted_dates = sorted(self._by_date.keys())

    def get(self, as_of_date: date) -> dict[str, Optional[float]]:
        if not self._sorted_dates:
            return _empty_features()

        # Collect up to 20 most recent dates <= as_of_date
        import bisect
        idx = bisect.bisect_right(self._sorted_dates, as_of_date)
        recent_dates = self._sorted_dates[max(0, idx - 20):idx]
        if not recent_dates:
            return _empty_features()

        # FII series (equity net investment in crores)
        fii_nets: list[tuple[date, float]] = []
        dii_nets: list[tuple[date, float]] = []
        for d in recent_dates:
            day = self._by_date[d]
            if "FII" in day and day["FII"].net_investment is not None:
                fii_nets.append((d, float(day["FII"].net_investment)))
            if "DII" in day and day["DII"].net_investment is not None:
                dii_nets.append((d, float(day["DII"].net_investment)))

        result: dict[str, Optional[float]] = {}

        # fii_net_1d: most recent FII net
        result["fii_net_1d"] = fii_nets[-1][1] if fii_nets else None

        # fii_net_5d: rolling 5d sum
        result["fii_net_5d"] = (
            round(sum(v for _, v in fii_nets[-5:]), 2) if len(fii_nets) >= 1 else None
        )

        # fii_net_20d: rolling 20d sum
        result["fii_net_20d"] = (
            round(sum(v for _, v in fii_nets), 2) if len(fii_nets) >= 1 else None
        )

        # dii_net_1d: most recent DII net
        result["dii_net_1d"] = dii_nets[-1][1] if dii_nets else None

        # fii_dii_ratio: FII_5d / |DII_5d| (capped at ±10 to prevent extreme outliers)
        fii_5d = result["fii_net_5d"]
        dii_5d = sum(v for _, v in dii_nets[-5:]) if len(dii_nets) >= 1 else None
        if fii_5d is not None and dii_5d is not None and abs(dii_5d) > 1.0:
            ratio = fii_5d / abs(dii_5d)
            result["fii_dii_ratio"] = round(max(-10.0, min(10.0, ratio)), 4)
        else:
            result["fii_dii_ratio"] = None

        # institutional_flow_signal: majority signal from both FII and DII
        # Use the pre-computed flow_signal column when available
        signal_map = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}
        signals = []
        today_data = self._by_date.get(recent_dates[-1], {})
        for cat in ("FII", "DII"):
            if cat in today_data:
                sig = (getattr(today_data[cat], "flow_signal", None) or "").upper()
                if sig in signal_map:
                    signals.append(signal_map[sig])
        if signals:
            result["institutional_flow_signal"] = round(float(np.mean(signals)), 2)
        elif fii_5d is not None:
            # Derive from net: positive 5d net = bullish
            result["institutional_flow_signal"] = 1.0 if fii_5d > 100 else (-1.0 if fii_5d < -100 else 0.0)
        else:
            result["institutional_flow_signal"] = None

        return {k: (round(float(v), 4) if v is not None else None) for k, v in result.items()}


def load_fii_dii_cache() -> Optional[FIIDIICache]:
    """
    Load all FII/DII rows from DB into an in-memory cache.
    Call once per feature generation run and pass to compute_fii_dii_features().
    Returns None if DB is unavailable or table is empty.
    """
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import FIIDIIFlow

        with get_db() as db:
            rows = (
                db.query(FIIDIIFlow)
                .filter(FIIDIIFlow.segment.in_(["equity", "total", None]))
                .order_by(FIIDIIFlow.flow_date.asc())
                .all()
            )
        if not rows:
            return None
        return FIIDIICache(rows)
    except Exception:
        return None

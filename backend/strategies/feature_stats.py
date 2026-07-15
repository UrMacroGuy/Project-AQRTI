"""
Feature Quantile Stats
Real-distribution quantiles for generator threshold sampling — Phase E of
the 2026-07-15c strategy generator upgrade. Replaces hardcoded uniform
threshold ranges with samples drawn from the ACTUAL measured distribution
of a feature across the curated universe, so generated thresholds land
where real data actually is instead of an arbitrary guessed band.

In-process TTL cache (~1 day) — quantiles move slowly and a fresh DB query
per generated candidate would be wasteful; generate_candidates() produces
dozens to hundreds of candidates per cycle.
"""

from __future__ import annotations

import sys, os, time
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import numpy as np
from sqlalchemy.orm import Session

from aqrti.database.models import FeatureValue
from aqrti.config.settings import get_settings
from aqrti.utils.logger import get_logger

log = get_logger("feature_stats")

CACHE_TTL_SECONDS = 24 * 3600   # ~1 day — quantiles move slowly
QUANTILE_LEVELS = (0.10, 0.25, 0.50, 0.75, 0.90)

_cache: dict[str, dict] = {}   # feature_name -> {"quantiles": {...}, "ts": float}


def get_feature_quantiles(db: Session, feature: str) -> Optional[dict[str, float]]:
    """
    Return {"q10":.., "q25":.., "q50":.., "q75":.., "q90":..} for `feature`,
    computed from real FeatureValue rows scoped to the curated universe.
    Returns None if the DB has no data for this feature (honest gap — caller
    must fall back to hardcoded ranges, never fabricate a distribution).
    """
    cached = _cache.get(feature)
    if cached and (time.time() - cached["ts"]) < CACHE_TTL_SECONDS:
        return cached["quantiles"]

    try:
        symbols = get_settings().universe_clean
        rows = (
            db.query(FeatureValue.value)
            .filter(
                FeatureValue.feature_name == feature,
                FeatureValue.symbol.in_(symbols),
                FeatureValue.value.isnot(None),
            )
            .all()
        )
    except Exception as exc:
        log.warning("feature_stats: DB query failed for %s: %s", feature, exc)
        return None

    values = [r[0] for r in rows if r[0] is not None]
    if len(values) < 30:
        # Too few real observations to trust a quantile estimate — honest
        # gap, caller falls back to hardcoded ranges.
        return None

    arr = np.asarray(values, dtype=float)
    quantiles = {
        f"q{int(level * 100)}": float(np.quantile(arr, level))
        for level in QUANTILE_LEVELS
    }
    _cache[feature] = {"quantiles": quantiles, "ts": time.time()}
    return quantiles


def clear_cache() -> None:
    """Test/debug helper — force the next call to re-query the DB."""
    _cache.clear()

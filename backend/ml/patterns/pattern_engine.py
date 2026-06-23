"""
AQRTI Pattern Engine
For each symbol, finds the top-5 most similar historical situations,
then looks up what actually happened after those situations.

Output per similar situation:
  - similarity_score
  - actual_return_5d (what happened)
  - actual_return_10d
  - was_bullish (binary)
  - outperformed_nifty (binary)

Aggregated output:
  - expected_return  (similarity-weighted average actual return)
  - win_rate         (fraction of similar situations that were positive)
  - pattern_confidence (mean similarity × sample size factor)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np

from aqrti.database.engine import get_db
from aqrti.utils.logger import get_logger
from ml.patterns.similarity_search import find_similar_situations

log = get_logger("pattern_engine")

TOP_K            = 5
MIN_SIMILAR      = 3       # minimum matches needed for reliable stats
LOOKBACK_DAYS    = 1200    # historical window to search in


def _get_actual_return(db, symbol: str, from_date: date, horizon: int) -> Optional[float]:
    """Look up actual N-day return for (symbol, from_date) from price data."""
    from aqrti.database.models import DailyPrice
    rows = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= from_date)
        .order_by(DailyPrice.date.asc())
        .limit(horizon + 1)
        .all()
    )
    if len(rows) < horizon + 1:
        return None
    close_t  = rows[0][0]
    close_tn = rows[horizon][0]
    if not close_t or close_t <= 0:
        return None
    return round(((close_tn / close_t) - 1.0) * 100.0, 4)


def _get_nifty_return(db, from_date: date, horizon: int) -> Optional[float]:
    """Look up actual N-day return for NIFTY50 from index_data."""
    from aqrti.database.models import IndexData
    rows = (
        db.query(IndexData.close)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date >= from_date)
        .order_by(IndexData.date.asc())
        .limit(horizon + 1)
        .all()
    )
    if len(rows) < horizon + 1:
        return None
    c0 = rows[0][0]
    cn = rows[horizon][0]
    if not c0 or c0 <= 0:
        return None
    return ((cn / c0) - 1.0) * 100.0


def analyze_similar_situations(
    similar: list[dict],
    db,
) -> list[dict]:
    """
    For each similar situation, look up what actually happened.
    Enriches each dict with outcome fields.
    """
    enriched = []
    for item in similar:
        sym   = item["symbol"]
        dt    = date.fromisoformat(item["date"])

        r5  = _get_actual_return(db, sym, dt, 5)
        r10 = _get_actual_return(db, sym, dt, 10)
        n5  = _get_nifty_return(db, dt, 5)

        outperformed = None
        if r5 is not None and n5 is not None:
            outperformed = r5 > n5

        enriched.append({
            **item,
            "actual_return_5d":    r5,
            "actual_return_10d":   r10,
            "nifty_return_5d":     round(n5, 4) if n5 is not None else None,
            "was_bullish":         (r5 > 0) if r5 is not None else None,
            "outperformed_nifty":  outperformed,
        })

    return enriched


def aggregate_pattern_outcomes(enriched: list[dict]) -> dict:
    """
    Aggregate outcomes from all similar situations into summary statistics.
    Uses similarity-weighted averaging.
    """
    valid = [e for e in enriched if e.get("actual_return_5d") is not None]
    if not valid:
        return {
            "expected_return":    None,
            "win_rate":           None,
            "outperform_rate":    None,
            "pattern_confidence": 0.0,
            "sample_size":        0,
        }

    sims    = np.array([e["similarity_score"] for e in valid], dtype=float)
    ret5s   = np.array([e["actual_return_5d"] for e in valid], dtype=float)
    bullish = np.array([1 if e["was_bullish"] else 0 for e in valid], dtype=float)
    outperf = np.array([
        1 if e.get("outperformed_nifty") else 0
        for e in valid
    ], dtype=float)

    # Similarity-weighted averages
    total_sim = sims.sum()
    if total_sim <= 0:
        weights = np.ones(len(sims)) / len(sims)
    else:
        weights = sims / total_sim

    expected_return  = float(np.dot(weights, ret5s))
    win_rate         = float(np.dot(weights, bullish))
    outperform_rate  = float(np.dot(weights, outperf))

    # Confidence: mean similarity × log-scaled sample size
    mean_sim = float(sims.mean())
    size_factor = float(np.log1p(len(valid)) / np.log1p(TOP_K))
    pattern_confidence = float(np.clip(mean_sim * size_factor, 0.0, 1.0))

    return {
        "expected_return":    round(expected_return, 4),
        "win_rate":           round(win_rate, 4),
        "outperform_rate":    round(outperform_rate, 4),
        "pattern_confidence": round(pattern_confidence, 4),
        "sample_size":        len(valid),
    }


def run_pattern_search(
    symbol: str,
    features: dict[str, float],
    feature_cols: list[str],
    version: int = 1,
    save_to_db: bool = True,
) -> dict:
    """
    Full pattern search pipeline for one symbol.

    Returns:
        {
          symbol, similar_situations (list), outcomes (aggregated dict),
          expected_return, win_rate, outperform_rate, pattern_confidence
        }
    """
    with get_db() as db:
        similar = find_similar_situations(
            current_features = features,
            feature_cols     = feature_cols,
            db               = db,
            symbol           = symbol,
            top_k            = TOP_K,
            days             = LOOKBACK_DAYS,
            version          = version,
        )

        if not similar:
            return {
                "symbol":              symbol,
                "similar_situations":  [],
                "outcomes":            {},
                "expected_return":     None,
                "win_rate":            None,
                "outperform_rate":     None,
                "pattern_confidence":  0.0,
            }

        enriched  = analyze_similar_situations(similar, db)
        outcomes  = aggregate_pattern_outcomes(enriched)

        if save_to_db and len([e for e in enriched if e.get("actual_return_5d") is not None]) >= MIN_SIMILAR:
            _save_pattern_matches(db, symbol, enriched, outcomes)

    return {
        "symbol":             symbol,
        "similar_situations": enriched,
        "outcomes":           outcomes,
        **{k: outcomes.get(k) for k in ("expected_return", "win_rate", "outperform_rate", "pattern_confidence")},
    }


def _save_pattern_matches(db, symbol: str, enriched: list[dict], outcomes: dict) -> None:
    """Persist pattern matches to the pattern_matches table."""
    try:
        import json
        from datetime import datetime
        from aqrti.database.models import PatternMatch

        row = PatternMatch(
            symbol              = symbol,
            search_date         = date.today(),
            similar_situations  = json.dumps(enriched[:TOP_K]),
            expected_return     = outcomes.get("expected_return"),
            win_rate            = outcomes.get("win_rate"),
            outperform_rate     = outcomes.get("outperform_rate"),
            pattern_confidence  = outcomes.get("pattern_confidence"),
            sample_size         = outcomes.get("sample_size", 0),
            computed_at         = datetime.utcnow(),
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        log.error("Failed to save pattern matches for %s: %s", symbol, exc)

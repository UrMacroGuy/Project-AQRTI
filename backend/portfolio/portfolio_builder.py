"""
Portfolio Builder (Phase 4B + 4D)
Generates the daily target portfolio from predictions + risk filters.

Supports 4 construction methods:
  confidence_weighted  — weight ∝ confidence (default)
  risk_adjusted        — inverse-volatility weighting
  equal_weight         — uniform allocation
  top_n                — equal weight, top N only

Output:
  {
    method, weights: {symbol: pct}, candidates: [...],
    totalExposure, cashAllocation, regime, date
  }
"""

from __future__ import annotations

import sys
import os
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.utils.logger import get_logger

log = get_logger("portfolio_builder")

_DEFAULT_METHOD = "confidence_weighted"


def build_target_portfolio(
    db:          Session,
    version:     int = 1,
    method:      str = _DEFAULT_METHOD,
    top_n:       int = 12,
    strategy_id: str | None = None,
) -> dict:
    """
    Build today's target portfolio.

    Returns dict:
      {method, weights, candidates, totalExposure, cashAllocation, regime, date}
    """
    today = date.today()

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from portfolio.risk_allocator import get_investable_candidates
    from portfolio.position_sizing import (
        confidence_based_sizing,
        risk_based_sizing,
        equal_weight_sizing,
    )

    candidates, max_expo = get_investable_candidates(
        db, today, version=version, top_n=top_n, strategy_id=strategy_id
    )

    if not candidates:
        log.warning("No investable candidates for %s", today)
        return {
            "method":          method,
            "weights":         {},
            "candidates":      [],
            "totalExposure":   0.0,
            "cashAllocation":  100.0,
            "regime":          "UNKNOWN",
            "date":            str(today),
        }

    if method == "risk_adjusted":
        weights = risk_based_sizing(candidates, max_exposure=max_expo)
    elif method in ("equal_weight", "top_n"):
        weights = equal_weight_sizing(candidates, max_exposure=max_expo)
    else:
        weights = confidence_based_sizing(candidates, max_exposure=max_expo)

    total_expo    = sum(weights.values())
    cash_alloc    = max(0.0, 100.0 - total_expo)

    log.info(
        "Portfolio built: method=%s  stocks=%d  exposure=%.1f%%  cash=%.1f%%",
        method, len(weights), total_expo, cash_alloc,
    )
    return {
        "method":         method,
        "weights":        weights,
        "candidates":     candidates,
        "totalExposure":  round(total_expo, 2),
        "cashAllocation": round(cash_alloc, 2),
        "date":           str(today),
    }


def get_allocation_view(db: Session, version: int = 1, method: str = _DEFAULT_METHOD) -> list[dict]:
    """
    Return the current target allocation as a sorted display list.
    Includes a cash row.
    """
    result  = build_target_portfolio(db, version=version, method=method)
    weights = result.get("weights", {})
    rows    = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    display = [
        {"symbol": sym, "weightPct": round(wt, 2), "type": "equity"}
        for sym, wt in rows
    ]
    display.append({
        "symbol":    "CASH",
        "weightPct": round(result["cashAllocation"], 2),
        "type":      "cash",
    })
    return display

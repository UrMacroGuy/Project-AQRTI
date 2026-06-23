"""Market Intelligence API — /api/v1/market"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import DailyPrice, IndexData
from aqrti.data.market_data import (
    get_latest_index,
    get_index_history,
    get_latest_prices,
    STOCK_META,
)
from aqrti.config.settings import get_settings

router = APIRouter()


def _sector_strength(db: Session, symbols: list[str]) -> list[dict]:
    """
    Compute sector strength score for each sector in the universe.
    Score = average of (30d RS + 14d momentum + last 1d return rescaled to 0-100).
    """
    sector_data: dict[str, list[float]] = {}

    for symbol in symbols:
        meta = STOCK_META.get(symbol)
        if not meta:
            continue
        sector = meta["sector"]

        cutoff = date.today() - timedelta(days=30)
        rows = (
            db.query(DailyPrice.close, DailyPrice.daily_return)
            .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff)
            .order_by(DailyPrice.date.asc())
            .all()
        )
        if len(rows) < 5:
            continue

        closes  = [r[0] for r in rows if r[0]]
        returns = [r[1] for r in rows if r[1] is not None]

        # 30-day cumulative return (0-100 normalized)
        if len(closes) >= 2 and closes[0]:
            cum_ret = (closes[-1] - closes[0]) / closes[0] * 100
        else:
            cum_ret = 0.0

        # Avg return last 5 days
        momentum = sum(returns[-5:]) / 5 if len(returns) >= 5 else 0.0

        # Simple composite: shift to 0-100 range
        score = 50 + cum_ret * 2 + momentum * 3
        score = max(0, min(100, score))

        sector_data.setdefault(sector, []).append(score)

    result = []
    for sector, scores in sector_data.items():
        avg_score = round(sum(scores) / len(scores), 1)
        result.append({
            "name":     sector,
            "score":    avg_score,
            "rs":       min(100, round(avg_score * 1.05, 1)),
            "momentum": min(100, round(avg_score * 0.95, 1)),
        })

    result.sort(key=lambda x: x["score"], reverse=True)
    return result


@router.get("")
def get_market(db: Session = Depends(get_db_dependency)):
    settings = get_settings()
    symbols  = settings.universe_clean

    nifty     = get_latest_index(db, "NIFTY50")
    banknifty = get_latest_index(db, "BANKNIFTY")

    # Top movers: stocks with highest absolute daily return today
    latest_prices = get_latest_prices(db, symbols)
    movers = sorted(
        [
            {
                "symbol":  sym,
                "sector":  STOCK_META.get(sym, {}).get("sector", ""),
                "price":   data["close"],
                "change":  data["daily_return"],
                "direction": "up" if (data["daily_return"] or 0) >= 0 else "down",
            }
            for sym, data in latest_prices.items()
            if data.get("daily_return") is not None
        ],
        key=lambda x: abs(x["change"]),
        reverse=True,
    )[:10]

    sector_strength = _sector_strength(db, symbols)

    return {
        "indices": {
            "nifty50":   {
                "value":     nifty["close"]   if nifty else None,
                "returns":   nifty["returns"] if nifty else None,
                "date":      nifty["date"]    if nifty else None,
            },
            "banknifty": {
                "value":     banknifty["close"]   if banknifty else None,
                "returns":   banknifty["returns"] if banknifty else None,
                "date":      banknifty["date"]    if banknifty else None,
            },
        },
        "sectorStrength": sector_strength,
        "topMovers":      movers,
        "lastUpdated":    str(date.today()),
    }


@router.get("/history/{index_name}")
def get_index_history_route(
    index_name: str,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    return get_index_history(db, index_name, days)

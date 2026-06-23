"""
AQRTI API — /api/v1/market-regime
Market regime classification and history.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import MarketRegime, SentimentRecord

router = APIRouter()


@router.get("")
def current_regime(db: Session = Depends(get_db_dependency)):
    """Return the latest market regime classification."""
    row = (
        db.query(MarketRegime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    if not row:
        # Fallback: derive from NIFTY data if no regime has been computed yet
        return _fallback_regime(db)

    return {
        "date":            str(row.date),
        "regime":          row.regime,
        "confidence":      row.confidence,
        "nifty_trend":     row.nifty_trend,
        "breadth_pct":     row.breadth_pct,
        "volatility_pct":  row.volatility_pct,
        "sentiment_score": row.sentiment_score,
        "signal_summary":  _parse_signals(row.signal_summary),
    }


@router.get("/history")
def regime_history(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    """Return market regime history for the last N days."""
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(MarketRegime)
        .filter(MarketRegime.date >= cutoff)
        .order_by(MarketRegime.date.asc())
        .all()
    )
    return [
        {
            "date":            str(r.date),
            "regime":          r.regime,
            "confidence":      r.confidence,
            "sentiment_score": r.sentiment_score,
            "breadth_pct":     r.breadth_pct,
        }
        for r in rows
    ]


# ── Fallback when sentiment pipeline hasn't run yet ───────────
def _fallback_regime(db: Session) -> dict:
    """
    Compute a basic regime from NIFTY50 returns when no explicit regime exists.
    This is only used before the sentiment pipeline has ever run.
    """
    from aqrti.database.models import IndexData
    rows = (
        db.query(IndexData)
        .filter(IndexData.index_name == "NIFTY50")
        .order_by(IndexData.date.desc())
        .limit(22)
        .all()
    )
    if len(rows) < 6:
        return {"date": str(date.today()), "regime": "UNKNOWN", "confidence": 0.0,
                "nifty_trend": None, "breadth_pct": None, "volatility_pct": None,
                "sentiment_score": 50.0, "signal_summary": {}}

    rows = list(reversed(rows))
    ret5  = (rows[-1].close - rows[-6].close) / rows[-6].close * 100 if rows[-6].close else 0
    ret21 = (rows[-1].close - rows[-22].close) / rows[-22].close * 100 if len(rows) >= 22 and rows[-22].close else 0

    if ret21 > 5:
        regime, conf = "BULL MARKET", 70.0
    elif ret21 < -5:
        regime, conf = "BEAR MARKET", 70.0
    elif abs(ret21) < 2:
        regime, conf = "SIDEWAYS", 60.0
    else:
        regime, conf = "SIDEWAYS", 55.0

    return {
        "date":            str(date.today()),
        "regime":          regime,
        "confidence":      conf,
        "nifty_trend":     "UP" if ret5 > 1 else "DOWN" if ret5 < -1 else "FLAT",
        "breadth_pct":     None,
        "volatility_pct":  None,
        "sentiment_score": 50.0 + ret21 * 1.5,
        "signal_summary":  {"nifty_return_21d": round(ret21, 2), "nifty_return_5d": round(ret5, 2)},
    }


def _parse_signals(signal_str: str | None) -> dict:
    if not signal_str:
        return {}
    import json
    try:
        return json.loads(signal_str)
    except Exception:
        return {}

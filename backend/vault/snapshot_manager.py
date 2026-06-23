"""
AQRTI Vault — Daily Market Snapshot
Captures complete market state: regime, prices, sentiment, features, knowledge score.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from aqrti.database.models import (
    MarketSnapshot, DailyPrice, MarketRegime, SentimentRecord,
    KnowledgeScore,
)


def archive_market_snapshot(db: Session, target_date: date) -> dict:
    existing = db.query(MarketSnapshot).filter(
        MarketSnapshot.snapshot_date == target_date
    ).first()
    if existing:
        return {"status": "already_exists", "snapshot_date": str(target_date)}

    # Regime
    regime_row = (
        db.query(MarketRegime)
        .filter(MarketRegime.date <= target_date)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    regime       = regime_row.regime          if regime_row else "UNKNOWN"
    regime_conf  = float(regime_row.confidence) if regime_row and regime_row.confidence else None

    # Nifty proxy — use NIFTY50 or ^NSEI
    nifty_close = None
    nifty_ret1d = None
    nifty_ret5d = None
    nifty_vol   = None

    nifty_price = (
        db.query(DailyPrice)
        .filter(DailyPrice.symbol.in_(["^NSEI", "NIFTY50"]), DailyPrice.date == target_date)
        .first()
    )
    if nifty_price:
        nifty_close = nifty_price.close
        nifty_ret1d = nifty_price.daily_return
        nifty_vol   = None  # DailyPrice has no volatility_20d column

        prev5 = (
            db.query(DailyPrice)
            .filter(
                DailyPrice.symbol == nifty_price.symbol,
                DailyPrice.date < target_date,
            )
            .order_by(DailyPrice.date.desc())
            .offset(4)
            .first()
        )
        if prev5 and prev5.close and nifty_close:
            nifty_ret5d = (nifty_close - prev5.close) / prev5.close * 100

    # Sentiment — SentimentRecord uses timestamp (DateTime), filter by date range
    sent_rows = (
        db.query(SentimentRecord)
        .filter(
            SentimentRecord.timestamp >= target_date,
            SentimentRecord.timestamp < target_date + timedelta(days=1),
        )
        .all()
    )
    avg_sentiment = (
        sum(r.score for r in sent_rows if r.score is not None)
        / max(len(sent_rows), 1)
    ) if sent_rows else None

    # Advance/Decline ratio
    prices_today = (
        db.query(DailyPrice)
        .filter(DailyPrice.date == target_date)
        .all()
    )
    advances = sum(1 for p in prices_today if p.daily_return and p.daily_return > 0)
    declines  = sum(1 for p in prices_today if p.daily_return and p.daily_return < 0)
    ad_ratio  = advances / max(declines, 1) if declines else None

    stocks_snapshot = [
        {
            "symbol": p.symbol,
            "close":  p.close,
            "ret_1d": p.daily_return,
            "volume": p.volume,
        }
        for p in prices_today[:200]
    ]

    # Knowledge score
    ks_row = (
        db.query(KnowledgeScore)
        .order_by(KnowledgeScore.date.desc())
        .first()
    )
    knowledge_score = float(ks_row.overall_score) if ks_row and ks_row.overall_score else None

    snap = MarketSnapshot(
        snapshot_date    = target_date,
        regime           = regime,
        regime_conf      = regime_conf,
        nifty_close      = nifty_close,
        nifty_return_1d  = nifty_ret1d,
        nifty_return_5d  = nifty_ret5d,
        nifty_volatility = nifty_vol,
        market_sentiment = avg_sentiment,
        advance_decline  = ad_ratio,
        stocks_json      = json.dumps(stocks_snapshot),
        knowledge_score  = knowledge_score,
    )
    db.add(snap)

    return {
        "status":         "created",
        "snapshot_date":  str(target_date),
        "regime":         regime,
        "stocks_captured": len(stocks_snapshot),
        "knowledge_score": knowledge_score,
    }


def get_snapshot(db: Session, target_date: date) -> dict | None:
    row = db.query(MarketSnapshot).filter(
        MarketSnapshot.snapshot_date == target_date
    ).first()
    if not row:
        return None
    return _to_dict(row)


def get_snapshot_range(db: Session, start: date, end: date) -> list[dict]:
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.snapshot_date.between(start, end))
        .order_by(MarketSnapshot.snapshot_date.asc())
        .all()
    )
    return [_to_dict(r) for r in rows]


def _to_dict(r: MarketSnapshot) -> dict:
    try:
        stocks = json.loads(r.stocks_json) if r.stocks_json else []
    except Exception:
        stocks = []
    return {
        "id":              r.id,
        "snapshot_date":   str(r.snapshot_date),
        "regime":          r.regime,
        "regime_conf":     r.regime_conf,
        "nifty_close":     r.nifty_close,
        "nifty_return_1d": r.nifty_return_1d,
        "nifty_return_5d": r.nifty_return_5d,
        "nifty_volatility":r.nifty_volatility,
        "market_sentiment":r.market_sentiment,
        "advance_decline": r.advance_decline,
        "knowledge_score": r.knowledge_score,
        "stocks_count":    len(stocks),
        "created_at":      r.created_at.isoformat() if r.created_at else None,
    }

"""
AQRTI Market Sentiment
Aggregates sector sentiments into a single market-level signal.
Also determines the market regime (BULL | BEAR | SIDEWAYS | VOLATILE)
and writes to the market_regimes table.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import MarketRegime
from aqrti.utils.logger import get_logger
from sentiment.company_sentiment import SentimentResult

log = get_logger("market_sentiment")


def compute_market_sentiment(
    sector_results: dict[str, SentimentResult],
    breadth_pct: Optional[float] = None,   # % stocks above EMA50 (from feature store)
    nifty_return_21d: Optional[float] = None,
    volatility_pct: Optional[float] = None,
) -> SentimentResult:
    """
    Aggregate all sector sentiments → single market sentiment.
    breadth_pct, nifty_return_21d, volatility_pct are optional enrichment signals.
    """
    if not sector_results:
        return _default_market_sentiment()

    n = len(sector_results)
    results = list(sector_results.values())

    avg_score        = sum(r.score       for r in results) / n
    avg_velocity     = sum(r.velocity    for r in results) / n
    avg_acceleration = sum(r.acceleration for r in results) / n
    avg_confidence   = sum(r.confidence  for r in results) / n
    avg_positive     = sum(r.positive_pct for r in results) / n
    avg_negative     = sum(r.negative_pct for r in results) / n
    avg_neutral      = sum(r.neutral_pct  for r in results) / n

    # Incorporate price-based signals into score if available
    if nifty_return_21d is not None:
        # Blend: 70% sentiment, 30% price signal
        price_signal = 50 + nifty_return_21d * 2  # map return% to 0-100 approx
        price_signal = max(0.0, min(100.0, price_signal))
        avg_score    = avg_score * 0.70 + price_signal * 0.30

    if breadth_pct is not None:
        # Blend breadth into score
        avg_score = avg_score * 0.80 + breadth_pct * 0.20

    avg_score = max(0.0, min(100.0, avg_score))

    return SentimentResult(
        entity       = "MARKET",
        entity_type  = "market",
        score        = round(avg_score, 2),
        velocity     = round(avg_velocity, 4),
        acceleration = round(avg_acceleration, 4),
        confidence   = round(avg_confidence, 2),
        news_count   = sum(r.news_count for r in results),
        positive_pct = round(avg_positive, 1),
        negative_pct = round(avg_negative, 1),
        neutral_pct  = round(avg_neutral, 1),
        computed_at  = datetime.utcnow(),
    )


def determine_regime(
    market_sentiment: SentimentResult,
    nifty_return_21d: Optional[float] = None,
    breadth_pct: Optional[float] = None,
    volatility_pct: Optional[float] = None,
) -> tuple[str, float]:
    """
    Determine market regime and confidence.
    Returns (regime_string, confidence_0_100).

    Regime rules (in priority order):
      VOLATILE  : volatility_pct > 30 OR (velocity < -0.3 AND breadth < 30)
      BULL      : score > 60 AND nifty_return_21d > 2 AND breadth > 55
      BEAR      : score < 40 AND nifty_return_21d < -2 AND breadth < 45
      SIDEWAYS  : everything else
    """
    score    = market_sentiment.score
    velocity = market_sentiment.velocity

    # VOLATILE check
    high_vol = volatility_pct is not None and volatility_pct > 30
    panic    = velocity < -0.3 and (breadth_pct is not None and breadth_pct < 30)
    if high_vol or panic:
        conf = 70.0 + (volatility_pct - 30) * 0.5 if high_vol else 65.0
        return "VOLATILE", round(min(95.0, conf), 1)

    # BULL check
    bull_sent   = score > 60
    bull_price  = nifty_return_21d is not None and nifty_return_21d > 2
    bull_breath = breadth_pct is None or breadth_pct > 55
    if bull_sent and bull_price and bull_breath:
        conf = 60 + (score - 60) * 1.5
        return "BULL MARKET", round(min(95.0, conf), 1)

    # BEAR check
    bear_sent  = score < 40
    bear_price = nifty_return_21d is not None and nifty_return_21d < -2
    bear_brd   = breadth_pct is None or breadth_pct < 45
    if bear_sent and bear_price and bear_brd:
        conf = 60 + (40 - score) * 1.5
        return "BEAR MARKET", round(min(95.0, conf), 1)

    return "SIDEWAYS", 55.0


def save_market_regime(
    db: Session,
    regime: str,
    confidence: float,
    market_sentiment: SentimentResult,
    nifty_trend: Optional[str] = None,
    breadth_pct: Optional[float] = None,
    volatility_pct: Optional[float] = None,
) -> MarketRegime:
    """Upsert today's market regime row."""
    today = date.today()
    existing = db.query(MarketRegime).filter_by(date=today).first()

    signals = {
        "sentiment_score": market_sentiment.score,
        "velocity":        market_sentiment.velocity,
        "news_count":      market_sentiment.news_count,
    }
    if breadth_pct is not None:
        signals["breadth_pct"] = breadth_pct
    if volatility_pct is not None:
        signals["volatility_pct"] = volatility_pct

    if existing:
        existing.regime          = regime
        existing.confidence      = confidence
        existing.nifty_trend     = nifty_trend
        existing.breadth_pct     = breadth_pct
        existing.volatility_pct  = volatility_pct
        existing.sentiment_score = market_sentiment.score
        existing.signal_summary  = json.dumps(signals)
        row = existing
    else:
        row = MarketRegime(
            date            = today,
            regime          = regime,
            confidence      = confidence,
            nifty_trend     = nifty_trend,
            breadth_pct     = breadth_pct,
            volatility_pct  = volatility_pct,
            sentiment_score = market_sentiment.score,
            signal_summary  = json.dumps(signals),
        )
        db.add(row)

    db.commit()
    log.info("Market regime saved: %s (conf=%.1f)", regime, confidence)
    return row


def _default_market_sentiment() -> SentimentResult:
    return SentimentResult(
        entity="MARKET", entity_type="market",
        score=50.0, velocity=0.0, acceleration=0.0,
        confidence=0.0, news_count=0,
        positive_pct=0.0, negative_pct=0.0, neutral_pct=100.0,
        computed_at=datetime.utcnow(),
    )

"""
Predictions / Opportunity Rankings API — /api/v1/predictions
Returns live ensemble predictions from the ML pipeline.
Falls back to last 7 days if no predictions exist for today.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import Prediction, SentimentRecord, ConfidenceHistory, PatternMatch
from aqrti.data.market_data import STOCK_META

router = APIRouter()


@router.get("")
def get_predictions(
    min_conf:  float   = Query(default=0.0,  ge=0, le=100),
    direction: str     = Query(default="all"),
    limit:     int     = Query(default=20,   ge=1, le=100),
    db:        Session = Depends(get_db_dependency),
):
    """
    Ranked prediction list.
    Sorted by confidence descending.
    """
    cutoff = date.today() - timedelta(days=7)
    q = (
        db.query(Prediction)
        .filter(
            Prediction.date       >= cutoff,
            Prediction.confidence >= min_conf,
        )
        .order_by(Prediction.confidence.desc())
    )
    if direction != "all":
        q = q.filter(Prediction.direction == direction.capitalize())

    preds = q.limit(limit).all()

    result = []
    for i, p in enumerate(preds, start=1):
        meta = STOCK_META.get(p.symbol, {})

        sent_row = (
            db.query(SentimentRecord.score)
            .filter(SentimentRecord.entity == p.symbol, SentimentRecord.entity_type == "stock")
            .order_by(SentimentRecord.timestamp.desc())
            .first()
        )
        sentiment_score = sent_row[0] if sent_row else None

        conf_row = (
            db.query(ConfidenceHistory)
            .filter_by(symbol=p.symbol, prediction_date=p.date)
            .first()
        )
        confidence_detail = None
        if conf_row:
            confidence_detail = {
                "category":   conf_row.confidence_category,
                "components": json.loads(conf_row.component_scores_json or "{}"),
            }

        result.append({
            "rank":             i,
            "symbol":           p.symbol,
            "name":             meta.get("name", p.symbol),
            "sector":           meta.get("sector", ""),
            "direction":        p.direction,
            "confidence":       p.confidence,
            "confidenceDetail": confidence_detail,
            "expectedReturn":   p.expected_return,
            "risk":             p.risk_level,
            "sentimentScore":   sentiment_score,
            "positionSize":     f"{p.position_size:.0f}%" if p.position_size else (
                # Kelly-lite sizing: scale from 2% (conf=65) to 8% (conf=85+)
                f"{min(8.0, max(2.0, (p.confidence - 65) * 0.3 + 2.0)):.1f}%" if p.confidence and p.confidence >= 65 else "1.0%"
            ),
            "date":             str(p.date),
            "reasoning":        p.reasoning,
            "modelVersion":     p.model_version,
        })

    return result


@router.get("/symbol/{symbol}")
def get_symbol_prediction(
    symbol: str,
    db:     Session = Depends(get_db_dependency),
):
    """Full prediction detail for a single symbol."""
    p = (
        db.query(Prediction)
        .filter_by(symbol=symbol)
        .order_by(Prediction.date.desc())
        .first()
    )
    if not p:
        return {"symbol": symbol, "available": False}

    meta = STOCK_META.get(symbol, {})

    conf_row = (
        db.query(ConfidenceHistory)
        .filter_by(symbol=symbol, prediction_date=p.date)
        .first()
    )

    pat_row = (
        db.query(PatternMatch)
        .filter_by(symbol=symbol, search_date=p.date)
        .first()
    )

    pattern_data = None
    if pat_row:
        pattern_data = {
            "expectedReturn":    pat_row.expected_return,
            "winRate":           pat_row.win_rate,
            "outperformRate":    pat_row.outperform_rate,
            "patternConfidence": pat_row.pattern_confidence,
            "sampleSize":        pat_row.sample_size,
            "similarSituations": json.loads(pat_row.similar_situations or "[]"),
        }

    return {
        "symbol":          symbol,
        "name":            meta.get("name", symbol),
        "sector":          meta.get("sector", ""),
        "available":       True,
        "date":            str(p.date),
        "direction":       p.direction,
        "confidence":      p.confidence,
        "expectedReturn":  p.expected_return,
        "risk":            p.risk_level,
        "reasoning":       p.reasoning,
        "modelVersion":    p.model_version,
        "confidence_detail": {
            "score":      conf_row.confidence_score        if conf_row else None,
            "category":   conf_row.confidence_category     if conf_row else None,
            "components": json.loads(conf_row.component_scores_json or "{}") if conf_row else {},
        },
        "pattern": pattern_data,
    }


@router.get("/summary")
def get_prediction_summary(db: Session = Depends(get_db_dependency)):
    """
    Aggregate stats across today's predictions:
    bullish count, bearish count, avg confidence, top 3 by confidence.
    """
    today  = date.today()
    cutoff = today - timedelta(days=7)
    preds  = db.query(Prediction).filter(Prediction.date >= cutoff).all()

    if not preds:
        return {"available": False}

    bullish  = [p for p in preds if p.direction == "Bullish"]
    bearish  = [p for p in preds if p.direction == "Bearish"]
    neutral  = [p for p in preds if p.direction == "Neutral"]
    confs    = [p.confidence for p in preds if p.confidence is not None]

    return {
        "available":       True,
        "total":           len(preds),
        "bullish":         len(bullish),
        "bearish":         len(bearish),
        "neutral":         len(neutral),
        "avgConfidence":   round(sum(confs) / len(confs), 1) if confs else None,
        "topPredictions":  [
            {"symbol": p.symbol, "direction": p.direction, "confidence": p.confidence}
            for p in sorted(preds, key=lambda x: x.confidence or 0, reverse=True)[:3]
        ],
        "lastUpdated": str(max((p.date for p in preds), default=today)),
    }

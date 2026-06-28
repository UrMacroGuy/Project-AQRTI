"""
Predictions / Opportunity Rankings API — /api/v1/predictions
Returns live ensemble predictions from the ML pipeline.
Falls back to last 7 days if no predictions exist for today.

Also exposes:
  GET /api/v1/predictions/today        — top-5 actionable trade signals with SL/TP
  GET /api/v1/predictions/model-health — 7-day model accuracy for DO NOT TRADE gate
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import (
    Prediction, SentimentRecord, ConfidenceHistory, PatternMatch,
    DailyPrice, StrategyV2, ModelDriftHistory,
)
from aqrti.data.market_data import STOCK_META

# ── Signal grade thresholds ───────────────────────────────────
GRADE_A_MIN   = 80.0
GRADE_B_MIN   = 65.0
GRADE_C_MIN   = 60.0   # below this → not returned in /today
MAX_SIGNALS   = 5
# Model health: if 7-day rolling accuracy is below this, show DO NOT TRADE
MODEL_ACCURACY_GATE = 0.52   # 52%

# ── Default SL/TP if no promoted strategy found ───────────────
DEFAULT_SL_PCT = 8.0    # -8%
DEFAULT_TP_PCT = 12.0   # +12%


def _get_latest_close(db: Session, symbol: str) -> float | None:
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return float(row[0]) if row and row[0] else None


def _get_best_strategy_params(db: Session) -> dict:
    """Return SL%, TP%, win_rate, trade_count, name from the top promoted strategy."""
    row = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.status.in_(["promoted", "active"]),
            StrategyV2.dsl_json.isnot(None),
        )
        .order_by(StrategyV2.fitness_score.desc())
        .first()
    )
    if not row:
        return {
            "sl_pct": DEFAULT_SL_PCT, "tp_pct": DEFAULT_TP_PCT,
            "win_rate": None, "trade_count": None,
            "name": None, "family": None,
        }
    dsl = json.loads(row.dsl_json) if row.dsl_json else {}
    return {
        "sl_pct":      dsl.get("stop_loss_pct")   or DEFAULT_SL_PCT,
        "tp_pct":      dsl.get("take_profit_pct") or DEFAULT_TP_PCT,
        "win_rate":    row.win_rate,
        "trade_count": row.trade_count,
        "name":        row.name,
        "family":      row.family,
        "regime":      dsl.get("allowed_regimes"),
    }


def _get_model_health(db: Session) -> dict:
    """Return 7-day rolling accuracy from model_drift_history. None if no data."""
    cutoff = date.today() - timedelta(days=7)
    rows = (
        db.query(ModelDriftHistory.accuracy)
        .filter(
            ModelDriftHistory.measured_date >= cutoff,
            ModelDriftHistory.accuracy.isnot(None),
        )
        .all()
    )
    if not rows:
        return {"accuracy": None, "do_not_trade": False, "status": "no_data"}
    avg_acc = sum(r[0] for r in rows) / len(rows)
    do_not_trade = avg_acc < MODEL_ACCURACY_GATE
    if avg_acc >= 0.55:
        status = "green"
    elif avg_acc >= MODEL_ACCURACY_GATE:
        status = "yellow"
    else:
        status = "red"
    return {
        "accuracy":     round(avg_acc * 100, 1),
        "do_not_trade": do_not_trade,
        "status":       status,
        "samples":      len(rows),
    }


def _signal_grade(confidence: float) -> str:
    if confidence >= GRADE_A_MIN:
        return "A"
    if confidence >= GRADE_B_MIN:
        return "B"
    return "C"

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


@router.get("/today")
def get_today_signals(db: Session = Depends(get_db_dependency)):
    """
    Top-5 actionable trade signals for today (or latest available date).

    Each signal includes:
    - Entry price (today's close), stop-loss price, target price, risk/reward ratio
    - Signal grade: A (≥80%), B (65–79%), C (60–64%)
    - Driving strategy: name, win rate, trade count, family
    - DO NOT TRADE flag if model accuracy < 52% over last 7 days

    Only Bullish signals with confidence ≥ 60 are returned. Max 5.
    """
    # ── Model health check ────────────────────────────────────
    health = _get_model_health(db)

    # ── Strategy params (SL/TP from best promoted strategy) ───
    strat = _get_best_strategy_params(db)

    # ── Find signals ──────────────────────────────────────────
    cutoff = date.today() - timedelta(days=7)
    preds = (
        db.query(Prediction)
        .filter(
            Prediction.date       >= cutoff,
            Prediction.direction  == "Bullish",
            Prediction.confidence >= GRADE_C_MIN,
        )
        .order_by(Prediction.confidence.desc())
        .limit(MAX_SIGNALS)
        .all()
    )

    if not preds:
        return {
            "date":         str(date.today()),
            "signals":      [],
            "signalCount":  0,
            "modelHealth":  health,
            "message":      "No signals today — check back after 3:30 PM IST",
        }

    signals = []
    for i, p in enumerate(preds, start=1):
        meta      = STOCK_META.get(p.symbol, {})
        last_price = _get_latest_close(db, p.symbol)

        # Entry is latest close; SL and TP derived from strategy params
        sl_pct = strat["sl_pct"]
        tp_pct = strat["tp_pct"]
        sl_price = round(last_price * (1 - sl_pct / 100), 2) if last_price else None
        tp_price = round(last_price * (1 + tp_pct / 100), 2) if last_price else None
        rr_ratio = round(tp_pct / sl_pct, 2) if sl_pct else None

        # Use strategy expectancy as expected return fallback
        exp_return = p.expected_return
        if not exp_return:
            exp_return = None   # never show a fake number

        signals.append({
            "rank":             i,
            "symbol":           p.symbol,
            "name":             meta.get("name", p.symbol),
            "sector":           meta.get("sector", ""),
            "signalGrade":      _signal_grade(p.confidence),
            "direction":        p.direction,
            "confidence":       round(p.confidence, 1),
            "expectedReturn":   round(exp_return, 2) if exp_return else None,
            "riskLevel":        p.risk_level or "Medium",
            # Entry / exit levels
            "lastPrice":        last_price,
            "stopLossPrice":    sl_price,
            "targetPrice":      tp_price,
            "stopLossPct":      -sl_pct,
            "takeProfitPct":    tp_pct,
            "riskRewardRatio":  rr_ratio,
            # Strategy driving this signal
            "strategyName":     strat["name"],
            "strategyWinRate":  round(strat["win_rate"], 1) if strat["win_rate"] else None,
            "strategyTrades":   strat["trade_count"],
            "strategyFamily":   strat["family"],
            "strategyRegimes":  strat["regime"],
            # Zerodha order hint
            "exchange":         "NSE",
            "orderType":        "CNC",
            # Signal metadata
            "date":             str(p.date),
            "reasoning":        p.reasoning,
            "modelVersion":     p.model_version,
        })

    return {
        "date":         str(date.today()),
        "signals":      signals,
        "signalCount":  len(signals),
        "modelHealth":  health,
        "doNotTrade":   health["do_not_trade"],
        "strategy": {
            "name":       strat["name"],
            "slPct":      strat["sl_pct"],
            "tpPct":      strat["tp_pct"],
            "winRate":    round(strat["win_rate"], 1) if strat["win_rate"] else None,
            "tradeCount": strat["trade_count"],
        },
    }


@router.get("/model-health")
def get_model_health(db: Session = Depends(get_db_dependency)):
    """
    7-day rolling model accuracy.
    Used to show the DO NOT TRADE banner when accuracy is below 52%.

    Returns:
    - accuracy: rolling average accuracy % (0–100)
    - do_not_trade: true if accuracy < 52%
    - status: "green" (≥55%), "yellow" (52–54%), "red" (<52%)
    """
    return _get_model_health(db)


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

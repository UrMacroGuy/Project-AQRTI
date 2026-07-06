"""
Multi-Agent Decision System
7 specialist agents + Moderator for consensus-based trading decisions.
Agents: Momentum, MeanReversion, Trend, Risk, Macro, Volatility, Portfolio
"""

from __future__ import annotations

import json, uuid
from datetime import date, timedelta
from typing import Optional
import sys, os

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    P9AgentOpinion as SpecialistAgentOpinion,
    P9ModeratorDecision as ModeratorDecision,
    DailyPrice, FeatureValue, MarketRegime, MarketBreadth,
    LessonLearned, StrategyV2,
)
from aqrti.utils.logger import get_logger

log = get_logger("multi_agent")

AGENT_WEIGHTS = {
    "Momentum":     0.18,
    "MeanReversion":0.13,
    "Trend":        0.17,
    "Risk":         0.20,
    "Macro":        0.12,
    "Volatility":   0.10,
    "Portfolio":    0.10,
}
AGREEMENT_THRESHOLD = 0.60   # fraction of agents that must agree


def _gen_id():
    return str(uuid.uuid4())[:16]


def _latest_feat(db, symbol, name, days=10):
    cutoff = date.today() - timedelta(days=days)
    r = db.query(FeatureValue.value).filter(
        FeatureValue.symbol == symbol, FeatureValue.feature_name == name,
        FeatureValue.date >= cutoff,
    ).order_by(FeatureValue.date.desc()).first()
    return float(r[0]) if r else None


def _price_change_pct(db, symbol, days=5):
    rows = db.query(DailyPrice.close).filter(
        DailyPrice.symbol == symbol,
        DailyPrice.date >= date.today() - timedelta(days=days + 5)
    ).order_by(DailyPrice.date.desc()).limit(days + 1).all()
    if len(rows) < 2:
        return None
    return float((rows[0][0] - rows[-1][0]) / rows[-1][0] * 100) if rows[-1][0] else None


def _current_regime(db):
    r = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
    return r[0] if r else "UNKNOWN"


def _breadth(db):
    r = db.query(MarketBreadth.above_ma20, MarketBreadth.total_stocks,
                 MarketBreadth.advance_decline_ratio).filter(
        MarketBreadth.universe == "NIFTY500"
    ).order_by(MarketBreadth.breadth_date.desc()).first()
    if not r:
        r = db.query(MarketBreadth.above_ma20, MarketBreadth.total_stocks,
                     MarketBreadth.advance_decline_ratio).order_by(
            MarketBreadth.breadth_date.desc()).first()
    if not r:
        return (50.0, 1.0)
    total = r[1] or 500
    pct = (r[0] / total * 100) if (r[0] and total > 0) else 50.0
    return (float(pct), float(r[2] or 1.0))


def _momentum_agent(db, symbol, regime) -> dict:
    rsi = _latest_feat(db, symbol, "rsi_14")
    mom = _latest_feat(db, symbol, "momentum_10d")
    chg5 = _price_change_pct(db, symbol, 5)
    signals = []
    if rsi:
        if rsi > 55: signals.append(("bullish", 0.7, f"RSI={rsi:.1f} above mid"))
        elif rsi < 45: signals.append(("bearish", 0.7, f"RSI={rsi:.1f} below mid"))
    if mom:
        if mom > 2: signals.append(("bullish", 0.8, f"Mom10d={mom:.2f}%"))
        elif mom < -2: signals.append(("bearish", 0.8, f"Mom10d={mom:.2f}%"))
    if chg5:
        if chg5 > 1.5: signals.append(("bullish", 0.6, f"5d chg={chg5:.2f}%"))
        elif chg5 < -1.5: signals.append(("bearish", 0.6, f"5d chg={chg5:.2f}%"))
    bull = sum(c for d, c, _ in signals if d == "bullish")
    bear = sum(c for d, c, _ in signals if d == "bearish")
    total = bull + bear or 1
    direction = "bullish" if bull > bear else ("bearish" if bear > bull else "neutral")
    confidence = max(bull, bear) / total
    return {"agent": "Momentum", "direction": direction, "confidence": round(confidence, 3),
            "reasoning": "; ".join(r for _, _, r in signals) or "No momentum signals",
            "regime_context": regime, "indicators_used": json.dumps(["rsi_14", "momentum_10d"])}


def _mean_reversion_agent(db, symbol, regime) -> dict:
    rsi = _latest_feat(db, symbol, "rsi_14")
    if not rsi:
        return {"agent": "MeanReversion", "direction": "neutral", "confidence": 0.5,
                "reasoning": "No RSI data", "regime_context": regime, "indicators_used": "[]"}
    if rsi < 30:
        direction, conf = "bullish", 0.75
        reason = f"RSI={rsi:.1f} oversold — mean reversion expected"
    elif rsi > 70:
        direction, conf = "bearish", 0.75
        reason = f"RSI={rsi:.1f} overbought — mean reversion expected"
    else:
        direction, conf = "neutral", 0.40
        reason = f"RSI={rsi:.1f} in normal range"
    return {"agent": "MeanReversion", "direction": direction, "confidence": conf,
            "reasoning": reason, "regime_context": regime,
            "indicators_used": json.dumps(["rsi_14"])}


def _trend_agent(db, symbol, regime) -> dict:
    ma_spread_val = _latest_feat(db, symbol, "ma_spread")
    adx = _latest_feat(db, symbol, "adx_14")
    reasons = []
    bull = bear = 0.0
    if ma_spread_val is not None:
        if ma_spread_val > 2.0: bull += 0.7; reasons.append(f"MA spread={ma_spread_val:.1f}% bullish")
        elif ma_spread_val < -2.0: bear += 0.7; reasons.append(f"MA spread={ma_spread_val:.1f}% bearish")
    if adx is not None:
        if adx > 25: bull += 0.8; reasons.append(f"ADX={adx:.0f} trending")
    total = bull + bear or 1
    direction = "bullish" if bull > bear else ("bearish" if bear > bull else "neutral")
    return {"agent": "Trend", "direction": direction, "confidence": round(max(bull, bear) / total, 3),
            "reasoning": "; ".join(reasons) or "Trend unclear",
            "regime_context": regime, "indicators_used": json.dumps(["ma_spread", "adx_14"])}


def _risk_agent(db, symbol, regime) -> dict:
    vol_raw = _latest_feat(db, symbol, "rolling_vol_21d")
    vol = vol_raw / 100.0 if vol_raw is not None else None
    reasons = []
    risk_score = 0.5
    if vol is not None:
        if vol > 0.35: risk_score += 0.2; reasons.append(f"High vol={vol:.2f}")
        elif vol < 0.15: risk_score -= 0.1; reasons.append(f"Low vol={vol:.2f}")
    if regime in ("HIGH_VOLATILITY", "CRISIS"):
        risk_score += 0.15; reasons.append(f"Risky regime={regime}")
    high_risk = risk_score > 0.65
    direction = "bearish" if high_risk else "neutral"
    confidence = min(0.95, risk_score)
    return {"agent": "Risk", "direction": direction, "confidence": round(confidence, 3),
            "reasoning": "; ".join(reasons) or "Risk normal",
            "regime_context": regime, "indicators_used": json.dumps(["rolling_vol_21d"])}


def _macro_agent(db, symbol, regime) -> dict:
    breadth_pct, adr = _breadth(db)
    reasons = []
    if breadth_pct > 65: reasons.append(f"Market breadth={breadth_pct:.0f}% bullish")
    elif breadth_pct < 35: reasons.append(f"Market breadth={breadth_pct:.0f}% bearish")
    if adr > 1.5: reasons.append(f"A/D ratio={adr:.2f} advancing")
    elif adr < 0.7: reasons.append(f"A/D ratio={adr:.2f} declining")
    direction = "bullish" if breadth_pct > 55 and adr > 1 else ("bearish" if breadth_pct < 45 else "neutral")
    confidence = 0.60 if direction != "neutral" else 0.40
    return {"agent": "Macro", "direction": direction, "confidence": confidence,
            "reasoning": "; ".join(reasons) or "Macro neutral",
            "regime_context": regime, "indicators_used": json.dumps(["breadth_pct", "advance_decline_ratio"])}


def _volatility_agent(db, symbol, regime) -> dict:
    vol_raw = _latest_feat(db, symbol, "rolling_vol_21d")
    vol = vol_raw / 100.0 if vol_raw is not None else None
    if vol is None:
        return {"agent": "Volatility", "direction": "neutral", "confidence": 0.5,
                "reasoning": "No vol data", "regime_context": regime, "indicators_used": "[]"}
    if vol > 0.40:
        direction, reason, conf = "bearish", f"Vol={vol:.2f} extreme — reduce exposure", 0.80
    elif vol < 0.12:
        direction, reason, conf = "neutral", f"Vol={vol:.2f} suppressed — conditions stable", 0.55
    else:
        direction, reason, conf = "neutral", f"Vol={vol:.2f} normal range", 0.50
    return {"agent": "Volatility", "direction": direction, "confidence": conf,
            "reasoning": reason, "regime_context": regime, "indicators_used": json.dumps(["rolling_vol_21d"])}


def _portfolio_agent(db, symbol, regime) -> dict:
    from aqrti.database.models import PaperTrade
    open_trades = db.query(PaperTrade).filter(PaperTrade.is_open == True).count()
    sym_exposure = db.query(PaperTrade).filter(PaperTrade.symbol == symbol, PaperTrade.is_open == True).count()
    if sym_exposure >= 2:
        direction, reason, conf = "bearish", f"Already {sym_exposure} open trades in {symbol}", 0.80
    elif open_trades > 20:
        direction, reason, conf = "bearish", f"Portfolio at {open_trades} open positions — crowded", 0.65
    else:
        direction, reason, conf = "bullish", f"Portfolio capacity available ({open_trades} open)", 0.60
    return {"agent": "Portfolio", "direction": direction, "confidence": conf,
            "reasoning": reason, "regime_context": regime, "indicators_used": json.dumps(["open_positions"])}


AGENTS = {
    "Momentum":      _momentum_agent,
    "MeanReversion": _mean_reversion_agent,
    "Trend":         _trend_agent,
    "Risk":          _risk_agent,
    "Macro":         _macro_agent,
    "Volatility":    _volatility_agent,
    "Portfolio":     _portfolio_agent,
}


def run_multi_agent_decision(db: Session, symbol: str,
                             strategy_id: Optional[str] = None,
                             context: Optional[dict] = None) -> dict:
    session_id = _gen_id()
    regime = _current_regime(db)
    log.info("Multi-agent decision: symbol=%s regime=%s", symbol, regime)

    opinions = []
    for name, fn in AGENTS.items():
        try:
            op = fn(db, symbol, regime)
            if not isinstance(op, dict) or "direction" not in op:
                raise ValueError(f"Agent returned invalid opinion: {op}")
            opinions.append(op)
            row = SpecialistAgentOpinion(
                session_id=session_id, agent_name=name,
                symbol=symbol, strategy_id=strategy_id,
                direction=op["direction"], confidence=op["confidence"],
                reasoning=op.get("reasoning", ""),
                regime_context=regime,
                indicators_used=op.get("indicators_used", "[]"),
                weight=AGENT_WEIGHTS.get(name, 0.14),
            )
            db.add(row)
        except Exception as exc:
            log.warning("Agent %s failed: %s", name, exc)

    if not opinions:
        log.warning("All agents failed for symbol=%s — returning neutral", symbol)
        db.rollback()
        return {"session_id": session_id, "symbol": symbol, "regime": regime,
                "direction": "neutral", "confidence": 50.0, "agreement_score": 0.0,
                "agent_summary": {}, "dissenting": [], "reasoning": "All agents failed."}

    # Moderator aggregation
    votes_bull = sum(AGENT_WEIGHTS.get(o["agent"], 0.14) for o in opinions if o["direction"] == "bullish")
    votes_bear = sum(AGENT_WEIGHTS.get(o["agent"], 0.14) for o in opinions if o["direction"] == "bearish")
    votes_neut = sum(AGENT_WEIGHTS.get(o["agent"], 0.14) for o in opinions if o["direction"] == "neutral")

    total = votes_bull + votes_bear + votes_neut or 1
    if votes_bull > votes_bear and votes_bull > votes_neut:
        final_direction = "bullish"; raw_conf = votes_bull / total
    elif votes_bear > votes_bull and votes_bear > votes_neut:
        final_direction = "bearish"; raw_conf = votes_bear / total
    else:
        final_direction = "neutral"; raw_conf = 0.5

    n_agree = sum(1 for o in opinions if o["direction"] == final_direction)
    agreement_score = n_agree / len(opinions) if opinions else 0.5
    final_confidence = raw_conf * (0.7 + 0.3 * agreement_score)

    agent_summary = {o["agent"]: {"direction": o["direction"], "confidence": o["confidence"]} for o in opinions}
    dissenting = [o["agent"] for o in opinions if o["direction"] != final_direction]
    reasoning = (f"Weighted votes: bull={votes_bull:.2f} bear={votes_bear:.2f} neut={votes_neut:.2f}. "
                 f"Agreement={agreement_score:.2f}. Dissenters: {', '.join(dissenting) or 'none'}.")

    mod = ModeratorDecision(
        session_id=session_id, symbol=symbol, strategy_id=strategy_id,
        final_direction=final_direction,
        final_confidence=round(final_confidence, 4),
        agreement_score=round(agreement_score, 4),
        bull_weight=round(votes_bull, 4),
        bear_weight=round(votes_bear, 4),
        neutral_weight=round(votes_neut, 4),
        agent_summary_json=json.dumps(agent_summary),
        dissenting_agents_json=json.dumps(dissenting),
        reasoning=reasoning,
        decision_date=date.today(),
    )
    db.add(mod)
    db.commit()

    log.info("Decision: %s → %s (conf=%.2f, agreement=%.2f)", symbol, final_direction, final_confidence, agreement_score)
    return {
        "session_id": session_id, "symbol": symbol, "regime": regime,
        "direction": final_direction,
        "confidence": round(final_confidence * 100, 1),
        "agreement_score": round(agreement_score, 4),
        "agent_summary": agent_summary, "dissenting": dissenting,
        "reasoning": reasoning,
    }


def multi_agent_agreement_score(db: Session, days: int = 30) -> float:
    """Used by knowledge_score.py"""
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(ModeratorDecision).filter(ModeratorDecision.decision_date >= cutoff).all()
    if not rows:
        return 0.0
    return round(float(np.mean([r.agreement_score for r in rows])), 4)


def get_recent_decisions(db: Session, symbol: Optional[str] = None, limit: int = 20) -> list:
    q = db.query(ModeratorDecision)
    if symbol:
        q = q.filter(ModeratorDecision.symbol == symbol)
    rows = q.order_by(ModeratorDecision.decision_date.desc()).limit(limit).all()
    return [{
        "session_id": r.session_id, "symbol": r.symbol,
        "direction": r.final_direction, "confidence": r.final_confidence,
        "agreement_score": r.agreement_score, "decision_date": str(r.decision_date),
        "reasoning": r.reasoning,
    } for r in rows]

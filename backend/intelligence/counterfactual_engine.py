"""
Counterfactual Learning Engine
Simulates alternative entry/exit decisions for every closed trade,
extracts lessons, and promotes them into LessonLearned.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional
import sys, os

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    PaperTrade, DailyPrice, MarketRegime,
    CounterfactualSimulation, CounterfactualLesson, LessonLearned,
)
from aqrti.utils.logger import get_logger

log = get_logger("counterfactual_engine")

MIN_RETURN_MAGNITUDE   = 0.3
MIN_SAMPLES_FOR_LESSON = 5
LESSON_CONFIDENCE_THRESHOLD = 0.6


def _price_on_or_after(db, symbol, d):
    r = db.query(DailyPrice.close).filter(DailyPrice.symbol == symbol, DailyPrice.date >= d).order_by(DailyPrice.date.asc()).first()
    return r[0] if r else None


def _price_on_or_before(db, symbol, d):
    r = db.query(DailyPrice.close).filter(DailyPrice.symbol == symbol, DailyPrice.date <= d).order_by(DailyPrice.date.desc()).first()
    return r[0] if r else None


def _regime(db, d):
    r = db.query(MarketRegime.regime).filter(MarketRegime.date <= d).order_by(MarketRegime.date.desc()).first()
    return r[0] if r else "UNKNOWN"


def _simulate(db, trade: PaperTrade) -> list:
    if not trade.entry_date or not trade.exit_date or trade.actual_return is None:
        return []
    entry_price = trade.entry_price or _price_on_or_after(db, trade.symbol, trade.entry_date)
    exit_price  = trade.exit_price  or _price_on_or_before(db, trade.symbol, trade.exit_date)
    if not entry_price or not exit_price or entry_price <= 0:
        return []
    orig = float((exit_price - entry_price) / entry_price * 100)
    regime = _regime(db, trade.entry_date)

    def _sim(scenario, se, sx, params):
        if not se or not sx or se <= 0:
            return None
        sr = float((sx - se) / se * 100)
        delta = sr - orig
        lesson = None
        if abs(delta) >= MIN_RETURN_MAGNITUDE:
            direction = "improved" if delta > 0 else "worsened"
            lesson = f"Scenario '{scenario}' {direction} return by {delta:+.2f}% vs actual {orig:.2f}% in {regime}."
        return {"source_type": "trade", "source_id": trade.id, "symbol": trade.symbol,
                "original_date": trade.entry_date, "scenario_type": scenario,
                "scenario_params_json": json.dumps(params), "original_return": orig,
                "simulated_return": sr, "return_delta": delta, "original_regime": regime,
                "lesson_generated": lesson, "confidence": 0.7}

    sims = []
    p_el = _price_on_or_after(db, trade.symbol, trade.entry_date + timedelta(days=1))
    s = _sim("entry_1d_later",     p_el, exit_price,  {"entry_shift": +1})
    if s: sims.append(s)
    p_ee = _price_on_or_before(db, trade.symbol, trade.entry_date - timedelta(days=1))
    s = _sim("entry_1d_earlier",   p_ee, exit_price,  {"entry_shift": -1})
    if s: sims.append(s)
    p_xe = _price_on_or_before(db, trade.symbol, trade.exit_date - timedelta(days=1))
    s = _sim("exit_1d_earlier",    entry_price, p_xe, {"exit_shift": -1})
    if s: sims.append(s)
    p_xl = _price_on_or_after(db, trade.symbol, trade.exit_date + timedelta(days=1))
    s = _sim("exit_1d_later",      entry_price, p_xl, {"exit_shift": +1})
    if s: sims.append(s)
    stop3  = entry_price * 0.97
    sl_exit = max(exit_price, stop3) if orig < 0 else exit_price
    s = _sim("stop_loss_tighter",  entry_price, sl_exit, {"stop_pct": -3.0})
    if s: sims.append(s)
    tp8 = entry_price * 1.08
    tp_exit = min(exit_price, tp8) if orig > 8 else exit_price
    s = _sim("take_profit_lower",  entry_price, tp_exit, {"tp_pct": 8.0})
    if s: sims.append(s)
    return sims


def run_counterfactual_analysis(db: Session, days: int = 14) -> dict:
    cutoff = date.today() - timedelta(days=days)
    trades = db.query(PaperTrade).filter(PaperTrade.is_open == False, PaperTrade.exit_date >= cutoff).all()
    log.info("Counterfactual: analyzing %d trades", len(trades))

    sims_written = 0
    scenario_deltas: dict = defaultdict(lambda: defaultdict(list))

    for trade in trades:
        simulations = _simulate(db, trade)
        for sim in simulations:
            ex = db.query(CounterfactualSimulation).filter(
                CounterfactualSimulation.source_type == "trade",
                CounterfactualSimulation.source_id == trade.id,
                CounterfactualSimulation.scenario_type == sim["scenario_type"],
            ).first()
            if ex:
                continue
            db.add(CounterfactualSimulation(**sim))
            sims_written += 1
            scenario_deltas[sim["scenario_type"]][sim["original_regime"]].append(sim["return_delta"])
    db.commit()

    lessons_written = 0
    for scenario, regime_deltas in scenario_deltas.items():
        for regime, deltas in regime_deltas.items():
            if len(deltas) < MIN_SAMPLES_FOR_LESSON:
                continue
            avg_delta = float(np.mean(deltas))
            if abs(avg_delta) < 0.5:
                continue
            direction = "improved" if avg_delta > 0 else "worsened"
            title = f"'{scenario}' consistently {direction} returns by {avg_delta:+.2f}% during {regime}"
            desc  = (f"Across {len(deltas)} simulations in {regime}, scenario '{scenario}' "
                     f"produced avg delta {avg_delta:+.2f}%.")
            conf  = min(0.9, 0.5 + len(deltas) / 50.0)
            ex = db.query(CounterfactualLesson).filter(
                CounterfactualLesson.scenario_type == scenario, CounterfactualLesson.regime == regime
            ).first()
            if ex:
                ex.avg_return_delta = avg_delta; ex.sample_count = len(deltas)
                ex.confidence = conf; ex.title = title; ex.description = desc
                ex.lesson_date = date.today()
            else:
                db.add(CounterfactualLesson(
                    lesson_date=date.today(), scenario_type=scenario, regime=regime,
                    title=title, description=desc, avg_return_delta=avg_delta,
                    sample_count=len(deltas), confidence=conf,
                ))
                lessons_written += 1
            if conf >= LESSON_CONFIDENCE_THRESHOLD and avg_delta > 0:
                already = db.query(LessonLearned).filter(LessonLearned.title == title).first()
                if not already:
                    db.add(LessonLearned(
                        lesson_date=date.today(), category="counterfactual", title=title,
                        description=desc, what_happened=f"Simulated '{scenario}' showed {avg_delta:+.2f}% improvement",
                        why_it_happened="Entry/exit timing adjustment affected outcome",
                        what_worked=scenario, what_failed="original approach",
                        recommendation=f"Apply '{scenario}' in {regime}",
                        severity="medium", regime=regime,
                    ))
    db.commit()
    log.info("Counterfactual: %d sims, %d lessons", sims_written, lessons_written)
    return {"status": "ok", "trades_analyzed": len(trades),
            "simulations_written": sims_written, "lessons_generated": lessons_written}


def get_counterfactual_lessons(db: Session, regime: Optional[str] = None, limit: int = 20) -> list:
    q = db.query(CounterfactualLesson)
    if regime:
        q = q.filter(CounterfactualLesson.regime == regime)
    rows = q.order_by(CounterfactualLesson.confidence.desc()).limit(limit).all()
    return [{"id": r.id, "lesson_date": str(r.lesson_date), "scenario_type": r.scenario_type,
             "regime": r.regime, "title": r.title, "description": r.description,
             "avg_return_delta": r.avg_return_delta, "sample_count": r.sample_count,
             "confidence": r.confidence} for r in rows]

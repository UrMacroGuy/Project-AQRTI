"""
AQRTI Vault — Historical Replay Engine
Reconstruct AQRTI's state at any past date from archived records.
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
    MarketSnapshot, PredictionArchive, PortfolioArchive,
    StrategyArchive, KnowledgeArchive, ResearchArchive,
)


def replay_date(db: Session, target_date: date) -> dict:
    """Return a full reconstructed state snapshot for target_date."""
    snap     = _get_market(db, target_date)
    preds    = _get_predictions(db, target_date)
    portfolio= _get_portfolio(db, target_date)
    strategies= _get_strategies(db, target_date)
    knowledge= _get_knowledge(db, target_date)
    research = _get_research(db, target_date)

    return {
        "replay_date":     str(target_date),
        "market_state":    snap,
        "predictions":     preds,
        "portfolio":       portfolio,
        "strategies":      strategies,
        "knowledge":       knowledge,
        "research":        research,
        "data_available":  bool(snap),
    }


def replay_range(db: Session, start: date, end: date) -> list[dict]:
    """Return a timeline of state snapshots from start to end (inclusive)."""
    results = []
    current = start
    while current <= end:
        results.append({
            "date":   str(current),
            "market": _get_market(db, current),
        })
        current += timedelta(days=1)
    return results


def compare_dates(db: Session, date_a: date, date_b: date) -> dict:
    """Side-by-side comparison of two historical dates."""
    state_a = replay_date(db, date_a)
    state_b = replay_date(db, date_b)

    def _delta(key, sub=None):
        a = state_a.get(key) or {}
        b = state_b.get(key) or {}
        if sub:
            a = a.get(sub)
            b = b.get(sub)
        if a is None or b is None:
            return None
        try:
            return round(float(b) - float(a), 4)
        except (TypeError, ValueError):
            return None

    return {
        "date_a":       str(date_a),
        "date_b":       str(date_b),
        "state_a":      state_a,
        "state_b":      state_b,
        "deltas": {
            "knowledge_score": _delta("market_state", "knowledge_score"),
            "nifty_close":     _delta("market_state", "nifty_close"),
            "market_sentiment":_delta("market_state", "market_sentiment"),
            "portfolio_value": _delta("portfolio",    "total_value"),
            "portfolio_pnl":   _delta("portfolio",    "total_pnl"),
            "strategy_count":  (len(state_b.get("strategies") or []) - len(state_a.get("strategies") or [])),
        },
    }


def _get_market(db: Session, d: date) -> dict | None:
    row = db.query(MarketSnapshot).filter(MarketSnapshot.snapshot_date == d).first()
    if not row:
        return None
    return {
        "snapshot_date":   str(row.snapshot_date),
        "regime":          row.regime,
        "regime_conf":     row.regime_conf,
        "nifty_close":     row.nifty_close,
        "nifty_return_1d": row.nifty_return_1d,
        "nifty_return_5d": row.nifty_return_5d,
        "nifty_volatility":row.nifty_volatility,
        "market_sentiment":row.market_sentiment,
        "advance_decline": row.advance_decline,
        "knowledge_score": row.knowledge_score,
    }


def _get_predictions(db: Session, d: date) -> list[dict]:
    rows = db.query(PredictionArchive).filter(
        PredictionArchive.prediction_date == d
    ).limit(100).all()
    return [
        {
            "symbol":       r.symbol,
            "direction":    r.direction,
            "confidence":   r.direction_conf,
            "magnitude":    r.magnitude_pct,
            "model":        r.model_name,
            "was_correct":  r.was_correct,
            "actual_return":r.actual_return,
        }
        for r in rows
    ]


def _get_portfolio(db: Session, d: date) -> dict | None:
    row = db.query(PortfolioArchive).filter(PortfolioArchive.archive_date == d).first()
    if not row:
        return None
    return {
        "archive_date":    str(row.archive_date),
        "total_value":     row.total_value,
        "cash":            row.cash,
        "invested":        row.invested,
        "total_pnl":       row.total_pnl,
        "total_return_pct":row.total_return_pct,
        "sharpe":          row.sharpe,
        "max_drawdown":    row.max_drawdown,
        "win_rate":        row.win_rate,
    }


def _get_strategies(db: Session, d: date) -> list[dict]:
    rows = db.query(StrategyArchive).filter(StrategyArchive.archive_date == d).all()
    return [
        {
            "strategy_id":  r.strategy_id,
            "name":         r.name,
            "family":       r.family,
            "generation":   r.generation,
            "fitness_score":r.fitness_score,
            "status":       r.status_at_archive,
        }
        for r in rows
    ]


def _get_knowledge(db: Session, d: date) -> dict | None:
    row = db.query(KnowledgeArchive).filter(KnowledgeArchive.archive_date == d).first()
    if not row:
        return None
    return {
        "archive_date":   str(row.archive_date),
        "knowledge_score":row.knowledge_score,
        "lessons_count":  row.lessons_count,
        "failures_count": row.failures_count,
    }


def _get_research(db: Session, d: date) -> list[dict]:
    rows = db.query(ResearchArchive).filter(
        ResearchArchive.archive_date == d
    ).order_by(ResearchArchive.archive_type).all()
    return [
        {
            "archive_type": r.archive_type,
            "agent_id":     r.agent_id,
            "title":        r.title,
            "summary":      r.summary,
            "urgency":      r.urgency,
        }
        for r in rows
    ]

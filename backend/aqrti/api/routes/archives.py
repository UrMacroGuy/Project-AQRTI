"""Archives API — /api/v1/archives  (prediction, portfolio, strategy, knowledge, research records)"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import (
    PredictionArchive, PortfolioArchive, StrategyArchive,
    KnowledgeArchive, ResearchArchive,
)

router = APIRouter()


@router.get("/predictions")
def archived_predictions(
    days:   int        = Query(default=30, ge=1, le=365),
    symbol: str | None = Query(default=None),
    limit:  int        = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(PredictionArchive).filter(PredictionArchive.prediction_date >= cutoff)
    if symbol:
        q = q.filter(PredictionArchive.symbol == symbol)
    rows = q.order_by(PredictionArchive.prediction_date.desc()).limit(limit).all()
    return {
        "total": len(rows),
        "predictions": [
            {
                "date":          str(r.prediction_date),
                "symbol":        r.symbol,
                "direction":     r.direction,
                "confidence":    r.direction_conf,
                "magnitude":     r.magnitude_pct,
                "model":         r.model_name,
                "regime":        r.regime_at,
                "was_correct":   r.was_correct,
                "actual_return": r.actual_return,
            }
            for r in rows
        ],
    }


@router.get("/portfolio")
def archived_portfolio(
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(PortfolioArchive).filter(
        PortfolioArchive.archive_date >= cutoff
    ).order_by(PortfolioArchive.archive_date.asc()).all()
    return {
        "total": len(rows),
        "records": [
            {
                "date":             str(r.archive_date),
                "total_value":      r.total_value,
                "cash":             r.cash,
                "invested":         r.invested,
                "total_pnl":        r.total_pnl,
                "total_return_pct": r.total_return_pct,
                "sharpe":           r.sharpe,
                "max_drawdown":     r.max_drawdown,
                "win_rate":         r.win_rate,
            }
            for r in rows
        ],
    }


@router.get("/strategies")
def archived_strategies(
    days:        int        = Query(default=30, ge=1, le=365),
    strategy_id: str | None = Query(default=None),
    status:      str | None = Query(default=None),
    limit:       int        = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(StrategyArchive).filter(StrategyArchive.archive_date >= cutoff)
    if strategy_id:
        q = q.filter(StrategyArchive.strategy_id == strategy_id)
    if status:
        q = q.filter(StrategyArchive.status_at_archive == status)
    rows = q.order_by(StrategyArchive.archive_date.desc()).limit(limit).all()
    return {
        "total": len(rows),
        "records": [
            {
                "strategy_id":  r.strategy_id,
                "date":         str(r.archive_date),
                "name":         r.name,
                "family":       r.family,
                "generation":   r.generation,
                "fitness_score":r.fitness_score,
                "status":       r.status_at_archive,
            }
            for r in rows
        ],
    }


@router.get("/knowledge")
def archived_knowledge(
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(KnowledgeArchive).filter(
        KnowledgeArchive.archive_date >= cutoff
    ).order_by(KnowledgeArchive.archive_date.asc()).all()
    return {
        "total": len(rows),
        "records": [
            {
                "date":           str(r.archive_date),
                "knowledge_score":r.knowledge_score,
                "lessons_count":  r.lessons_count,
                "failures_count": r.failures_count,
            }
            for r in rows
        ],
    }


@router.get("/research")
def archived_research(
    days:         int        = Query(default=30, ge=1, le=365),
    archive_type: str | None = Query(default=None),
    urgency:      str | None = Query(default=None),
    limit:        int        = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(ResearchArchive).filter(ResearchArchive.archive_date >= cutoff)
    if archive_type:
        q = q.filter(ResearchArchive.archive_type == archive_type)
    if urgency:
        q = q.filter(ResearchArchive.urgency == urgency)
    rows = q.order_by(ResearchArchive.archive_date.desc()).limit(limit).all()
    return {
        "total": len(rows),
        "records": [
            {
                "date":         str(r.archive_date),
                "archive_type": r.archive_type,
                "agent_id":     r.agent_id,
                "title":        r.title,
                "summary":      r.summary,
                "urgency":      r.urgency,
                "regime":       r.regime_at,
            }
            for r in rows
        ],
    }

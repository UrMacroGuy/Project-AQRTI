"""
AQRTI Historical Intelligence Vault — Vault Manager
Central orchestrator for all vault archival operations.
Run once daily after all pipeline steps complete.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from aqrti.database.engine import get_db


def run_daily_vault(target_date: date | None = None) -> dict:
    """Archive everything for target_date (default: today)."""
    from vault.snapshot_manager import archive_market_snapshot
    from vault.archive_manager import (
        archive_predictions, archive_portfolio,
        archive_strategies, archive_knowledge, archive_research,
    )

    target = target_date or date.today()
    results: dict = {"vault_date": str(target), "steps": {}, "status": "ok"}

    with get_db() as db:
        for name, fn, args in [
            ("market_snapshot",    archive_market_snapshot, (db, target)),
            ("prediction_archive", archive_predictions,     (db, target)),
            ("portfolio_archive",  archive_portfolio,       (db, target)),
            ("strategy_archive",   archive_strategies,      (db, target)),
            ("knowledge_archive",  archive_knowledge,       (db, target)),
            ("research_archive",   archive_research,        (db, target)),
        ]:
            try:
                results["steps"][name] = fn(*args)
                db.commit()
            except Exception as exc:
                db.rollback()
                results["steps"][name] = {"status": "error", "error": str(exc)}
                results["status"] = "partial"

    return results


def get_vault_summary(db: Session) -> dict:
    from aqrti.database.models import (
        MarketSnapshot, PredictionArchive, PortfolioArchive,
        StrategyArchive, KnowledgeArchive, ResearchArchive,
    )

    return {
        "market_snapshots":    db.query(MarketSnapshot).count(),
        "prediction_records":  db.query(PredictionArchive).count(),
        "portfolio_records":   db.query(PortfolioArchive).count(),
        "strategy_records":    db.query(StrategyArchive).count(),
        "knowledge_records":   db.query(KnowledgeArchive).count(),
        "research_records":    db.query(ResearchArchive).count(),
        "oldest_snapshot":     _oldest_date(db, MarketSnapshot, "snapshot_date"),
        "newest_snapshot":     _newest_date(db, MarketSnapshot, "snapshot_date"),
    }


def _oldest_date(db, model, col_name):
    row = db.query(model).order_by(getattr(model, col_name).asc()).first()
    if row:
        return str(getattr(row, col_name))
    return None


def _newest_date(db, model, col_name):
    row = db.query(model).order_by(getattr(model, col_name).desc()).first()
    if row:
        return str(getattr(row, col_name))
    return None

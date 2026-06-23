"""
AQRTI Self-Learning Dataset Builder — Phase 8.5E
Builds training datasets from AQRTI's own historical decisions:
predictions, confidence, trades, outcomes, lessons, failures, research, pattern matches.
AQRTI learns from its own history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("aqrti_history_builder")


@dataclass
class AQRTIHistoryDataset:
    dataset_type: str
    records: List[Dict[str, Any]]
    record_count: int
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.records) if self.records else pd.DataFrame()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_type": self.dataset_type,
            "record_count": self.record_count,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "metadata": self.metadata,
        }


def build_prediction_history_dataset(
    days_back: int = 365,
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset of all historical predictions with their actual outcomes."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)
        rows = db.execute(text("""
            SELECT p.date, p.symbol, p.direction, p.confidence, p.expected_return,
                   p.actual_return, p.success, p.regime, p.model_version,
                   p.sentiment_score, p.risk_level
            FROM predictions p
            WHERE p.date >= :cutoff AND p.actual_return IS NOT NULL
            ORDER BY p.date
            """),
            {"cutoff": cutoff},
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["date"] for r in records if r["date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="prediction_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"days_back": days_back, "generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_trade_history_dataset(
    days_back: int = 365,
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset of historical paper trades with outcomes."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)
        rows = db.execute(text("""
            SELECT symbol, entry_date, exit_date, entry_price, exit_price,
                   capital_deployed, gross_pnl, gross_pnl_pct, direction,
                   confidence, predicted_return, actual_return, exit_reason,
                   holding_days, sector
            FROM paper_trades
            WHERE entry_date >= :cutoff AND is_open = 0
            ORDER BY entry_date
            """),
            {"cutoff": cutoff},
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["entry_date"] for r in records if r["entry_date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="trade_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"days_back": days_back, "generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_failure_history_dataset(
    days_back: int = 365,
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset of all historical AQRTI failures."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)
        rows = db.execute(text("""
            SELECT failure_date, symbol, failure_category, failure_type, severity,
                   predicted_value, actual_value, confidence_at, regime_at,
                   root_cause, lesson
            FROM failure_records
            WHERE failure_date >= :cutoff
            ORDER BY failure_date
            """),
            {"cutoff": cutoff},
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["failure_date"] for r in records if r["failure_date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="failure_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"days_back": days_back, "generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_confidence_history_dataset(
    days_back: int = 365,
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset pairing confidence scores with actual outcomes."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)
        rows = db.execute(text("""
            SELECT ch.prediction_date, ch.symbol, ch.confidence_score,
                   ch.confidence_category, ch.model_agreement,
                   ch.historical_accuracy, ch.regime_confidence,
                   ch.signal_strength, ch.feature_completeness,
                   p.actual_return, p.success, p.direction
            FROM confidence_history ch
            LEFT JOIN predictions p ON p.symbol = ch.symbol AND p.date = ch.prediction_date
            WHERE ch.prediction_date >= :cutoff AND p.actual_return IS NOT NULL
            ORDER BY ch.prediction_date
            """),
            {"cutoff": cutoff},
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["prediction_date"] for r in records if r["prediction_date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="confidence_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"days_back": days_back, "generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_lesson_history_dataset(
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset of all lessons learned."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(text("""
            SELECT lesson_date, category, title, description,
                   what_happened, why_it_happened, what_worked, what_failed,
                   recommendation, severity, symbol, regime
            FROM lessons_learned ORDER BY lesson_date
            """)
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["lesson_date"] for r in records if r["lesson_date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="lesson_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_pattern_history_dataset(
    days_back: int = 365,
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset of historical pattern matches and their outcomes."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)
        rows = db.execute(text("""
            SELECT po.symbol, po.prediction_date, po.pattern_confidence,
                   po.predicted_return, po.actual_return_5d, po.actual_return_10d,
                   po.was_correct, po.outperformed_nifty, po.similarity_score,
                   po.regime_at
            FROM pattern_outcomes po
            WHERE po.prediction_date >= :cutoff
            ORDER BY po.prediction_date
            """),
            {"cutoff": cutoff},
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["prediction_date"] for r in records if r["prediction_date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="pattern_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"days_back": days_back, "generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_research_history_dataset(
    db: Optional[Session] = None,
) -> AQRTIHistoryDataset:
    """Build a dataset of all historical research findings."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(text("""
            SELECT finding_date, agent_id, category, subcategory,
                   title, description, evidence, implication, urgency, symbol, regime
            FROM research_findings ORDER BY finding_date
            """)
        ).fetchall()

        records = [dict(r._mapping) for r in rows]
        dates = [r["finding_date"] for r in records if r["finding_date"]] if records else []

        return AQRTIHistoryDataset(
            dataset_type="research_history",
            records=records,
            record_count=len(records),
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_all_aqrti_history_datasets(days_back: int = 365) -> Dict[str, AQRTIHistoryDataset]:
    """Build the complete AQRTI self-history dataset collection."""
    db = get_session_factory()()
    try:
        datasets = {
            "predictions": build_prediction_history_dataset(days_back, db),
            "trades": build_trade_history_dataset(days_back, db),
            "failures": build_failure_history_dataset(days_back, db),
            "confidence": build_confidence_history_dataset(days_back, db),
            "lessons": build_lesson_history_dataset(db),
            "patterns": build_pattern_history_dataset(days_back, db),
            "research": build_research_history_dataset(db),
        }
        total = sum(ds.record_count for ds in datasets.values())
        logger.info("AQRTI history datasets built: %d types, %d total records", len(datasets), total)
        return datasets
    finally:
        db.close()


def run_aqrti_history_pipeline(days_back: int = 365) -> Dict[str, Any]:
    """Full pipeline entry point."""
    logger.info("Starting AQRTI history dataset pipeline (days_back=%d)", days_back)
    datasets = build_all_aqrti_history_datasets(days_back)
    return {
        "status": "complete",
        "datasets": {k: ds.to_dict() for k, ds in datasets.items()},
        "total_records": sum(ds.record_count for ds in datasets.values()),
    }

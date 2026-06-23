"""
Research Dataset Builder — Phase 8.5H
Builds training datasets from AQRTI's accumulated research:
reports, lessons, strategy reports, drift reports, knowledge events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("research_dataset_builder")


@dataclass
class ResearchDataset:
    source_type: str
    records: List[Dict[str, Any]]
    record_count: int
    categories: List[str]
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.records) if self.records else pd.DataFrame()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "record_count": self.record_count,
            "categories": self.categories,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "metadata": self.metadata,
        }


def build_agent_reports_dataset(db: Optional[Session] = None) -> ResearchDataset:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            """
            SELECT ar.report_date, ar.agent_id, ar.category, ar.title,
                   ar.summary, ar.urgency, a.agent_type
            FROM agent_reports ar
            LEFT JOIN agents a ON a.agent_id = ar.agent_id
            ORDER BY ar.report_date
            """
        ).fetchall()
        records = [dict(r._mapping) for r in rows]
        dates = [r["report_date"] for r in records if r["report_date"]] if records else []
        cats = list({r["category"] for r in records if r.get("category")})
        return ResearchDataset(
            source_type="agent_reports",
            records=records,
            record_count=len(records),
            categories=cats,
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_research_briefs_dataset(db: Optional[Session] = None) -> ResearchDataset:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            """
            SELECT brief_date, title, market_summary, regime_at, knowledge_score
            FROM research_briefs ORDER BY brief_date
            """
        ).fetchall()
        records = [dict(r._mapping) for r in rows]
        dates = [r["brief_date"] for r in records if r["brief_date"]] if records else []
        return ResearchDataset(
            source_type="research_briefs",
            records=records,
            record_count=len(records),
            categories=["brief"],
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_strategy_research_dataset(db: Optional[Session] = None) -> ResearchDataset:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            """
            SELECT report_date, category, title, summary, recommendations
            FROM strategy_research_reports ORDER BY report_date
            """
        ).fetchall()
        records = [dict(r._mapping) for r in rows]
        dates = [r["report_date"] for r in records if r["report_date"]] if records else []
        cats = list({r["category"] for r in records if r.get("category")})
        return ResearchDataset(
            source_type="strategy_research",
            records=records,
            record_count=len(records),
            categories=cats,
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_drift_reports_dataset(db: Optional[Session] = None) -> ResearchDataset:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            """
            SELECT model_name, task, measured_date, drift_pct, drift_flag,
                   accuracy, auc_roc, ic, baseline_metric
            FROM model_drift_history ORDER BY measured_date
            """
        ).fetchall()
        records = [dict(r._mapping) for r in rows]
        dates = [r["measured_date"] for r in records if r["measured_date"]] if records else []
        return ResearchDataset(
            source_type="drift_reports",
            records=records,
            record_count=len(records),
            categories=["model_drift"],
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_knowledge_events_dataset(db: Optional[Session] = None) -> ResearchDataset:
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            """
            SELECT event_date, category, symbol, event_type, description,
                   outcome, magnitude, confidence_at, actual_result, regime
            FROM knowledge_events ORDER BY event_date
            """
        ).fetchall()
        records = [dict(r._mapping) for r in rows]
        dates = [r["event_date"] for r in records if r["event_date"]] if records else []
        cats = list({r["category"] for r in records if r.get("category")})
        return ResearchDataset(
            source_type="knowledge_events",
            records=records,
            record_count=len(records),
            categories=cats,
            date_range_start=str(min(dates)) if dates else None,
            date_range_end=str(max(dates)) if dates else None,
            metadata={"generated_at": datetime.utcnow().isoformat()},
        )
    finally:
        if own_session:
            db.close()


def build_all_research_datasets() -> Dict[str, ResearchDataset]:
    db = get_session_factory()()
    try:
        datasets = {
            "agent_reports": build_agent_reports_dataset(db),
            "research_briefs": build_research_briefs_dataset(db),
            "strategy_research": build_strategy_research_dataset(db),
            "drift_reports": build_drift_reports_dataset(db),
            "knowledge_events": build_knowledge_events_dataset(db),
        }
        total = sum(ds.record_count for ds in datasets.values())
        logger.info("Research datasets built: %d sources, %d total records", len(datasets), total)
        return datasets
    finally:
        db.close()


def run_research_dataset_pipeline() -> Dict[str, Any]:
    logger.info("Starting research dataset pipeline")
    datasets = build_all_research_datasets()
    return {
        "status": "complete",
        "datasets": {k: ds.to_dict() for k, ds in datasets.items()},
        "total_records": sum(ds.record_count for ds in datasets.values()),
    }

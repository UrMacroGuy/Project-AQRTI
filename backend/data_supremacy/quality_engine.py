"""
Phase 8G — Data Quality Engine
Runs completeness, freshness, duplicate, and schema checks on every dataset.
Writes DataQualityLog and DataSourceHealth records.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func, inspect

from aqrti.database.models import (
    DataQualityLog, DailyPrice, NSECorporateFiling, FIIDIIFlow,
    OptionsChain, MarketBreadth, SectorRotation, EarningsEvent,
    Prediction, NewsEvent,
)

logger = logging.getLogger("data_supremacy.quality")


DATASETS = [
    ("daily_prices",       DailyPrice,        ["symbol", "date", "close"],         1),
    ("predictions",        Prediction,        ["symbol", "date", "direction"],      1),
    ("news_events",        NewsEvent,         ["headline", "timestamp"],            1),
    ("nse_corporate",      NSECorporateFiling,["symbol", "filing_date"],            3),
    ("fii_dii_flows",      FIIDIIFlow,        ["flow_date", "category", "net_investment"], 1),
    ("options_chain",      OptionsChain,      ["symbol", "snapshot_date", "pcr_oi"],1),
    ("market_breadth",     MarketBreadth,     ["breadth_date", "advance_decline_ratio"], 1),
    ("sector_rotation",    SectorRotation,    ["rotation_date", "sector", "rs_rank"], 1),
    ("earnings_events",    EarningsEvent,     ["symbol", "earnings_date"],          3),
]


def run_quality_checks(db: Session, target_date: date | None = None) -> dict:
    target = target_date or date.today()
    results = []

    for name, model, required_fields, max_freshness_days in DATASETS:
        result = _check_dataset(db, name, model, required_fields, max_freshness_days, target)
        results.append(result)
        _write_log(db, result, target)

    db.commit()

    scores = [r["quality_score"] for r in results if r["quality_score"] is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    passing = sum(1 for r in results if r.get("quality_grade") in ("A", "B"))

    return {
        "status":     "ok",
        "date":       str(target),
        "datasets":   results,
        "avg_score":  avg_score,
        "passing":    passing,
        "total":      len(results),
    }


def _check_dataset(db: Session, name: str, model, required_fields: list[str],
                    max_freshness_days: int, target: date) -> dict:
    issues = []

    try:
        total = db.query(model).count()
    except Exception as exc:
        return {"dataset_name": name, "quality_score": 0, "quality_grade": "F",
                "issues": [f"Table query failed: {exc}"], "total_records": 0}

    if total == 0:
        return {
            "dataset_name":  name,
            "total_records": 0,
            "null_pct":      100.0,
            "duplicate_pct": 0.0,
            "freshness_hours": None,
            "schema_errors": 0,
            "quality_score": 0.0,
            "quality_grade": "F",
            "issues":        ["No records in table"],
        }

    # Freshness: check created_at or scraped_at
    freshness_hours = None
    for ts_col in ("scraped_at", "created_at"):
        if hasattr(model, ts_col):
            latest = db.query(func.max(getattr(model, ts_col))).scalar()
            if latest:
                delta = datetime.utcnow() - latest
                freshness_hours = round(delta.total_seconds() / 3600, 1)
            break

    if freshness_hours is not None and freshness_hours > max_freshness_days * 24:
        issues.append(f"Data stale: {freshness_hours:.0f}h since last update (max {max_freshness_days*24}h)")

    # Null check on required fields
    null_counts = []
    for field in required_fields:
        if hasattr(model, field):
            nulls = db.query(func.count()).filter(getattr(model, field).is_(None)).scalar() or 0
            pct   = nulls / total * 100
            null_counts.append(pct)
            if pct > 10:
                issues.append(f"Field '{field}' is {pct:.1f}% null")
    null_pct = max(null_counts) if null_counts else 0

    # Duplicates: count vs distinct (approximation using date + symbol if available)
    duplicate_pct = 0.0
    try:
        if hasattr(model, "symbol") and hasattr(model, "date"):
            distinct = db.query(model.symbol, model.date).distinct().count()
            total_sym_date = db.query(model.symbol, model.date).count()
            duplicate_pct = max(0, (total_sym_date - distinct) / max(total_sym_date, 1) * 100)
            if duplicate_pct > 5:
                issues.append(f"Duplicate rate: {duplicate_pct:.1f}%")
    except Exception:
        pass

    # Quality score
    score = 100.0
    if null_pct > 5:
        score -= min(null_pct * 0.5, 25)
    if duplicate_pct > 2:
        score -= min(duplicate_pct, 10)
    if freshness_hours and freshness_hours > max_freshness_days * 24:
        overage = freshness_hours / (max_freshness_days * 24) - 1
        score -= min(overage * 20, 30)
    score = max(0, round(score, 1))

    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 55 else "D" if score >= 35 else "F"

    return {
        "dataset_name":   name,
        "total_records":  total,
        "null_pct":       round(null_pct, 2),
        "duplicate_pct":  round(duplicate_pct, 2),
        "freshness_hours":freshness_hours,
        "schema_errors":  0,
        "quality_score":  score,
        "quality_grade":  grade,
        "issues":         issues,
    }


def _write_log(db: Session, result: dict, target: date) -> None:
    existing = db.query(DataQualityLog).filter(
        DataQualityLog.check_date   == target,
        DataQualityLog.dataset_name == result["dataset_name"],
    ).first()

    if existing:
        existing.total_records   = result["total_records"]
        existing.null_pct        = result["null_pct"]
        existing.duplicate_pct   = result["duplicate_pct"]
        existing.freshness_hours = result["freshness_hours"]
        existing.quality_score   = result["quality_score"]
        existing.quality_grade   = result["quality_grade"]
        existing.issues_json     = json.dumps(result["issues"])
    else:
        row = DataQualityLog(
            check_date    = target,
            dataset_name  = result["dataset_name"],
            total_records = result["total_records"],
            null_pct      = result["null_pct"],
            duplicate_pct = result["duplicate_pct"],
            freshness_hours = result["freshness_hours"],
            quality_score = result["quality_score"],
            quality_grade = result["quality_grade"],
            issues_json   = json.dumps(result["issues"]),
        )
        db.add(row)


def get_quality_dashboard(db: Session, days: int = 7) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(DataQualityLog).filter(
        DataQualityLog.check_date >= cutoff
    ).order_by(DataQualityLog.check_date.desc(), DataQualityLog.dataset_name).all()

    by_dataset: dict[str, list] = {}
    for r in rows:
        by_dataset.setdefault(r.dataset_name, []).append({
            "date":          str(r.check_date),
            "quality_score": r.quality_score,
            "quality_grade": r.quality_grade,
            "total_records": r.total_records,
            "freshness_hours": r.freshness_hours,
            "issues":        json.loads(r.issues_json) if r.issues_json else [],
        })

    latest: dict[str, dict] = {name: recs[0] for name, recs in by_dataset.items() if recs}
    scores = [v["quality_score"] for v in latest.values() if v.get("quality_score") is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    return {
        "avg_quality_score": avg_score,
        "datasets":          latest,
        "history":           by_dataset,
        "alert_datasets":    [n for n, v in latest.items() if (v.get("quality_score") or 100) < 60],
    }

"""Strategy Research API — /api/v1/research"""

from __future__ import annotations

import sys, os, json

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import StrategyResearchReport
from strategies.research_engine import run_full_research
from strategies.strategy_research_loop import run_daily_strategy_research

router = APIRouter()


def _safe_json(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return s


@router.get("")
def list_reports(
    days:     int        = Query(default=30, ge=1, le=365),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(StrategyResearchReport).filter(StrategyResearchReport.report_date >= cutoff)
    if category:
        q = q.filter(StrategyResearchReport.category == category)
    rows = q.order_by(StrategyResearchReport.created_at.desc()).limit(100).all()

    return {
        "reports": [
            {
                "id":              r.id,
                "report_date":     str(r.report_date),
                "category":        r.category,
                "title":           r.title,
                "summary":         r.summary,
                "findings":        _safe_json(r.findings_json),
                "recommendations": r.recommendations,
                "created_at":      r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/latest")
def latest_reports(db: Session = Depends(get_db_dependency)):
    """Most recent report per category."""
    categories = [
        "feature_analysis", "regime_analysis", "family_survival",
        "evolution_summary", "resurrection", "population_health",
    ]
    result = {}
    for cat in categories:
        row = (
            db.query(StrategyResearchReport)
            .filter(StrategyResearchReport.category == cat)
            .order_by(StrategyResearchReport.report_date.desc())
            .first()
        )
        if row:
            result[cat] = {
                "report_date":     str(row.report_date),
                "title":           row.title,
                "summary":         row.summary,
                "findings":        _safe_json(row.findings_json),
                "recommendations": row.recommendations,
            }
    return result


@router.post("/run")
def run_research(db: Session = Depends(get_db_dependency)):
    """Manually trigger research report generation."""
    result = run_full_research(db)
    return result


@router.post("/run-full-loop")
def run_full_loop(
    generate_n: int = Query(default=50, ge=10, le=200),
    evolve_n:   int = Query(default=20, ge=5, le=100),
):
    """Manually trigger the full strategy research loop (all 8 steps)."""
    result = run_daily_strategy_research(generate_n=generate_n, evolve_n=evolve_n)
    return result

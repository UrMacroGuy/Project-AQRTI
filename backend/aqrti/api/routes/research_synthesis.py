"""
Research Synthesis API — /api/v1/research-synthesis (read-only)

Thin GET-only surface over the `research_synthesis` table (LLM-derived
per-symbol daily thesis, always cited back to real source rows — see
backend/intelligence/research_synthesizer.py). No write endpoints here;
synthesis is produced by the research pipeline, not by API calls.
"""

from __future__ import annotations

import json
import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import ResearchSynthesis

router = APIRouter()


def _safe_json(s):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []


def _serialize(r: ResearchSynthesis) -> dict:
    return {
        "symbol":               r.symbol,
        "synthesis_date":       str(r.synthesis_date),
        "sentiment_score":      r.sentiment_score,
        "thesis_direction":     r.thesis_direction,
        "key_catalysts":        _safe_json(r.key_catalysts),
        "risk_flags":           _safe_json(r.risk_flags),
        "management_change_flag": r.management_change_flag,
        "source_event_ids":     _safe_json(r.source_event_ids),
        "model_used":           r.model_used,
        "confidence":           r.confidence,
        "created_at":           r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/latest")
def latest_synthesis(db: Session = Depends(get_db_dependency)):
    """Most recent research synthesis row per symbol."""
    rows = db.query(ResearchSynthesis).order_by(
        ResearchSynthesis.symbol, ResearchSynthesis.synthesis_date.desc()
    ).all()
    latest_by_symbol: dict[str, ResearchSynthesis] = {}
    for r in rows:
        if r.symbol not in latest_by_symbol:
            latest_by_symbol[r.symbol] = r
    return {"synthesis": [_serialize(r) for r in latest_by_symbol.values()]}


@router.get("/{symbol}")
def symbol_synthesis(
    symbol: str,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    """Recent research synthesis history for one symbol, newest first."""
    rows = (
        db.query(ResearchSynthesis)
        .filter(ResearchSynthesis.symbol == symbol.upper())
        .order_by(ResearchSynthesis.synthesis_date.desc())
        .limit(days)
        .all()
    )
    return {"symbol": symbol.upper(), "synthesis": [_serialize(r) for r in rows]}

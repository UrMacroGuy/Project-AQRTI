"""Research Briefs API — /api/v1/research-briefs"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from agents.daily_brief_generator import (
    get_today_brief, get_brief_by_date, list_briefs,
)

router = APIRouter()


@router.get("")
def list_research_briefs(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db_dependency),
):
    return {"briefs": list_briefs(db, limit=limit)}


@router.get("/today")
def get_today(db: Session = Depends(get_db_dependency)):
    brief = get_today_brief(db)
    if not brief:
        raise HTTPException(status_code=404, detail="No brief generated for today yet")
    return brief


@router.get("/{brief_date}")
def get_by_date(brief_date: str, db: Session = Depends(get_db_dependency)):
    try:
        d = date.fromisoformat(brief_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")
    brief = get_brief_by_date(db, d)
    if not brief:
        raise HTTPException(status_code=404, detail=f"No brief found for {brief_date}")
    return brief


@router.post("/generate")
def generate_brief():
    """Manually trigger the CRO agent to generate today's brief."""
    from agents.daily_brief_generator import generate_daily_brief
    result = generate_daily_brief()
    return result

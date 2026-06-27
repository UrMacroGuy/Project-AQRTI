from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.counterfactual_engine import (
    run_counterfactual_analysis, get_counterfactual_lessons,
)

router = APIRouter()


@router.post("/run")
def run_counterfactual(days: int = 14, db: Session = Depends(get_db)):
    return run_counterfactual_analysis(db, days=days)


@router.get("/lessons")
def lessons(regime: Optional[str] = None, limit: int = 20, db: Session = Depends(get_db)):
    return get_counterfactual_lessons(db, regime=regime, limit=limit)

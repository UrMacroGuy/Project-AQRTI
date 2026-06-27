from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.bayesian_uncertainty import (
    estimate_uncertainty, uncertainty_quality_score, get_latest_estimate,
)

router = APIRouter()


@router.post("/estimate")
def estimate(model_id: str, symbol: Optional[str] = None,
             base_confidence: float = 0.70, db: Session = Depends(get_db)):
    return estimate_uncertainty(db, model_id=model_id, symbol=symbol,
                                base_confidence=base_confidence)


@router.get("/latest/{model_id}")
def latest(model_id: str, db: Session = Depends(get_db)):
    r = get_latest_estimate(db, model_id)
    return r or {"error": "No estimates found", "model_id": model_id}


@router.get("/quality-score")
def quality_score(days: int = 30, db: Session = Depends(get_db)):
    return {"score": uncertainty_quality_score(db, days=days)}

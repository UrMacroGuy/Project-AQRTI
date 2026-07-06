from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.feature_discovery import (
    run_feature_discovery, get_approved_features, get_candidate_pipeline,
)

router = APIRouter()


@router.post("/run")
def run_discovery(db: Session = Depends(get_db)):
    return run_feature_discovery(db)


@router.get("/approved")
def approved_features(db: Session = Depends(get_db)):
    return get_approved_features(db)


@router.get("/pipeline")
def pipeline(db: Session = Depends(get_db)):
    return get_candidate_pipeline(db)

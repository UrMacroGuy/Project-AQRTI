from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.regime_discovery import (
    run_regime_discovery, get_todays_regime, get_regime_history, get_regime_stats,
)

router = APIRouter()


@router.post("/run")
def run_discovery(n_clusters: int = 6, db: Session = Depends(get_db)):
    return run_regime_discovery(db, n_clusters=n_clusters)


@router.get("/today")
def today_regime(db: Session = Depends(get_db)):
    return get_todays_regime(db) or {"regime_id": None, "label": "No data yet"}


@router.get("/history")
def regime_history(days: int = 90, db: Session = Depends(get_db)):
    return get_regime_history(db, days=days)


@router.get("/stats")
def regime_stats(db: Session = Depends(get_db)):
    return get_regime_stats(db)

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.hypothesis_engine import run_hypothesis_cycle, get_hypothesis_summary

router = APIRouter()


@router.post("/run")
def run_cycle(db: Session = Depends(get_db)):
    return run_hypothesis_cycle(db)


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    return get_hypothesis_summary(db)

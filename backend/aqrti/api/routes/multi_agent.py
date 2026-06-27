from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.multi_agent_decision import (
    run_multi_agent_decision, get_recent_decisions, multi_agent_agreement_score,
)

router = APIRouter()


@router.post("/decide")
def decide(symbol: str, strategy_id: Optional[str] = None, db: Session = Depends(get_db)):
    return run_multi_agent_decision(db, symbol=symbol, strategy_id=strategy_id)


@router.get("/decisions")
def decisions(symbol: Optional[str] = None, limit: int = 20, db: Session = Depends(get_db)):
    return get_recent_decisions(db, symbol=symbol, limit=limit)


@router.get("/agreement-score")
def agreement_score(days: int = 30, db: Session = Depends(get_db)):
    return {"score": multi_agent_agreement_score(db, days=days)}

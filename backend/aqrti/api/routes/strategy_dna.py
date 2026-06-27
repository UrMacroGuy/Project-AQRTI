from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.strategy_dna import sync_strategy_dna, find_similar_strategies, get_dna_profile

router = APIRouter()


@router.post("/sync")
def sync_dna(limit: int = 200, db: Session = Depends(get_db)):
    return sync_strategy_dna(db, limit=limit)


@router.get("/{strategy_id}/profile")
def dna_profile(strategy_id: str, db: Session = Depends(get_db)):
    p = get_dna_profile(db, strategy_id)
    return p or {"error": "No DNA found", "strategy_id": strategy_id}


@router.get("/{strategy_id}/similar")
def similar(strategy_id: str, top_n: int = 10, db: Session = Depends(get_db)):
    return find_similar_strategies(db, strategy_id, top_n=top_n)

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.champion_challenger import (
    run_arena_evaluation, rollback_champion, register_arena, get_arena_status,
)

router = APIRouter()


class RegisterArenaRequest(BaseModel):
    name: str
    champion_id: str
    challenger_ids: List[str]


@router.post("/evaluate")
def evaluate(arena_id: Optional[str] = None, db: Session = Depends(get_db)):
    return run_arena_evaluation(db, arena_id=arena_id)


@router.post("/rollback/{arena_id}")
def rollback(arena_id: str, db: Session = Depends(get_db)):
    return rollback_champion(db, arena_id=arena_id)


@router.post("/register")
def register(req: RegisterArenaRequest, db: Session = Depends(get_db)):
    return register_arena(db, req.name, req.champion_id, req.challenger_ids)


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return get_arena_status(db)

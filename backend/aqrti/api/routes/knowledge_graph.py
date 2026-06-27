from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from aqrti.database.engine import get_db_dependency as get_db
from intelligence.knowledge_graph_engine import (
    run_full_graph_update, query_graph, get_graph_summary,
)

router = APIRouter()


@router.post("/update")
def update_graph(db: Session = Depends(get_db)):
    return run_full_graph_update(db)


@router.get("/summary")
def graph_summary(db: Session = Depends(get_db)):
    return get_graph_summary(db)


@router.get("/query")
def graph_query(question: str, db: Session = Depends(get_db)):
    return query_graph(db, question)

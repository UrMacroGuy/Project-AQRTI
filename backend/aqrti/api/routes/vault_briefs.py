"""Vault Briefs API — /api/v1/vault-briefs  (stored markdown brief files)"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from fastapi import HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()

BRIEFS_DIR = os.path.join(backend_dir, "data", "briefs")


@router.get("")
def list_briefs():
    """List all saved daily brief markdown files."""
    if not os.path.exists(BRIEFS_DIR):
        return {"briefs": [], "total": 0}
    files = sorted(
        [f for f in os.listdir(BRIEFS_DIR) if f.startswith("daily_brief_") and f.endswith(".md")],
        reverse=True,
    )
    results = []
    for f in files[:60]:
        date_str = f.replace("daily_brief_", "").replace(".md", "")
        path = os.path.join(BRIEFS_DIR, f)
        results.append({
            "date":     date_str,
            "filename": f,
            "size_bytes": os.path.getsize(path),
        })
    return {"briefs": results, "total": len(results)}


@router.get("/{brief_date}")
def get_brief_markdown(brief_date: str):
    """Return the markdown content of a stored daily brief."""
    filename = f"daily_brief_{brief_date}.md"
    path = os.path.join(BRIEFS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"No brief file for {brief_date}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return PlainTextResponse(content=content, media_type="text/markdown")


@router.post("/{brief_date}/export")
def export_brief(brief_date: str, db: Session = Depends(get_db_dependency)):
    """Generate and save a brief markdown file from DB for the given date."""
    from vault.exporters import save_brief_markdown
    try:
        d = date.fromisoformat(brief_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD.")
    filepath = save_brief_markdown(db, d, BRIEFS_DIR)
    return {"status": "exported", "path": filepath, "date": brief_date}

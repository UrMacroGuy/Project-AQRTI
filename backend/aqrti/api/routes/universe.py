"""
Universe API — /api/v1/universe
Manage and download the global stock universe.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.data.global_universe import (
    GLOBAL_UNIVERSE,
    seed_global_universe,
    download_global_universe,
    get_universe_summary,
)

router = APIRouter()

# Track background download status
_DOWNLOAD_STATE = {
    "running": False,
    "last_result": None,
    "started_at": None,
    "error": None,
}
_STATE_LOCK = threading.Lock()


@router.get("/summary")
def universe_summary(db: Session = Depends(get_db_dependency)):
    """How many stocks are seeded and how much data is loaded."""
    return get_universe_summary(db)


@router.get("/list")
def universe_list(
    region: str = Query(default="all"),
    sector: str = Query(default="all"),
):
    """Return universe tickers with metadata, optionally filtered."""
    result = []
    for ticker, meta in GLOBAL_UNIVERSE.items():
        if region != "all" and meta.get("region") != region:
            continue
        if sector != "all" and meta.get("sector") != sector:
            continue
        result.append({"ticker": ticker, **meta})
    return result


@router.post("/seed")
def seed_universe(db: Session = Depends(get_db_dependency)):
    """Insert all global universe stocks into the Stock table (upsert)."""
    return seed_global_universe(db)


@router.post("/download")
def trigger_download(
    background_tasks: BackgroundTasks,
    years: int = Query(default=3, ge=1, le=10),
    region: str = Query(default="all"),
    workers: int = Query(default=4, ge=1, le=8),
    batch_size: int = Query(default=20, ge=5, le=50),
    db: Session = Depends(get_db_dependency),
):
    """
    Start a background download of global universe price data.
    - years: how many years of history (default 3)
    - region: filter to specific region (US/IN/UK/DE/JP/HK/AU/CA/CH/FR/etc) or 'all'
    - workers: parallel download threads (default 4)
    """
    with _STATE_LOCK:
        if _DOWNLOAD_STATE["running"]:
            return {
                "status": "already_running",
                "message": "Download already in progress. Check /universe/status for progress.",
            }

    # Filter tickers by region if requested
    if region == "all":
        symbols = list(GLOBAL_UNIVERSE.keys())
    else:
        symbols = [t for t, m in GLOBAL_UNIVERSE.items() if m.get("region") == region]

    start_date = date.today() - timedelta(days=int(years) * 365)

    def _run():
        with _STATE_LOCK:
            _DOWNLOAD_STATE["running"] = True
            _DOWNLOAD_STATE["started_at"] = str(date.today())
            _DOWNLOAD_STATE["error"] = None
            _DOWNLOAD_STATE["last_result"] = None

        try:
            from aqrti.database.engine import get_session_factory
            _db = get_session_factory()()
            try:
                # Seed universe metadata first
                seed_global_universe(_db)
                # Download price data
                result = download_global_universe(
                    _db,
                    symbols=symbols,
                    start_date=start_date,
                    workers=workers,
                    batch_size=batch_size,
                )
                with _STATE_LOCK:
                    _DOWNLOAD_STATE["last_result"] = result
            finally:
                _db.close()
        except Exception as exc:
            with _STATE_LOCK:
                _DOWNLOAD_STATE["error"] = str(exc)
        finally:
            with _STATE_LOCK:
                _DOWNLOAD_STATE["running"] = False

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "message": f"Downloading {len(symbols)} tickers ({region}) from {start_date}. Poll /universe/status for progress.",
        "tickers": len(symbols),
        "start_date": str(start_date),
        "workers": workers,
    }


@router.get("/status")
def download_status():
    """Check if a background download is running and its last result."""
    with _STATE_LOCK:
        return {
            "running":     _DOWNLOAD_STATE["running"],
            "started_at":  _DOWNLOAD_STATE["started_at"],
            "last_result": _DOWNLOAD_STATE["last_result"],
            "error":       _DOWNLOAD_STATE["error"],
        }


@router.get("/regions")
def list_regions():
    """Return all available regions and their ticker counts."""
    regions: dict[str, int] = {}
    for meta in GLOBAL_UNIVERSE.values():
        r = meta.get("region", "Unknown")
        regions[r] = regions.get(r, 0) + 1
    return dict(sorted(regions.items(), key=lambda x: -x[1]))

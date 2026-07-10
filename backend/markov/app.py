"""
Markov module — standalone FastAPI application.

Runs as its own process on its own port (default 8001), entirely separate
from the main AQRTI backend (port 8000). This is genuine process isolation,
not just code isolation: a crash, hang, or resource exhaustion in this
process can never take down the main backend, and vice versa.

Shares only the physical aqrti.db SQLite file (via markov.db, which reuses
aqrti.database.engine's connection helpers) — no shared FastAPI app, no
shared in-memory state, no shared boot sequence.

Run: python -m markov.app   OR   uvicorn markov.app:app --port 8001
"""

from __future__ import annotations

import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aqrti.utils.logger import get_logger

from markov.db import init_markov_schema
from markov.routes import router as markov_router

log = get_logger("markov.app")

app = FastAPI(title="AQRTI Markov Module", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(markov_router, prefix="/api/v1/markov", tags=["Markov"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "markov"}


@app.on_event("startup")
async def on_startup():
    log.info("Markov backend starting up...")
    init_markov_schema()

    def _deferred_update():
        time.sleep(1)
        try:
            from markov.pipeline import run_full_markov_update
            result = run_full_markov_update()
            log.info("Markov module update: %s", result)
        except Exception:
            log.exception("Markov module update failed on startup.")

    t = threading.Thread(target=_deferred_update, name="markov-startup-update", daemon=True)
    t.start()
    log.info("Markov backend ready.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("markov.app:app", host="127.0.0.1", port=8001, reload=False, log_level="info")

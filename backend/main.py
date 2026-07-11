"""
AQRTI Backend — Entry Point
Run: python main.py  OR  uvicorn main:app --reload
"""

from pathlib import Path
from dotenv import load_dotenv

# Load .env before importing anything that reads env vars at import/call time
# (see the matching note in aqrti/api/app.py — this is belt-and-suspenders
# since uvicorn's string-based app reference re-imports app.py in its own
# worker anyway, but costs nothing to be explicit here too).
load_dotenv(Path(__file__).resolve().parent / ".env")

import uvicorn
from aqrti.api.app import app
from aqrti.config.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "aqrti.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )

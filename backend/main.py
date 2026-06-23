"""
AQRTI Backend — Entry Point
Run: python main.py  OR  uvicorn main:app --reload
"""

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

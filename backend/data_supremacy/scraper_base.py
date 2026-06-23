"""
Data Supremacy — Scraper Base
Shared HTTP session, retry logic, change detection, schema validation.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import hashlib
import json
import time
import logging
from datetime import datetime, date
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("data_supremacy")


def make_session(
    retries: int = 4,
    backoff_factor: float = 1.5,
    status_forcelist: tuple = (429, 500, 502, 503, 504),
    timeout: int = 20,
) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    session._timeout = timeout
    return session


def safe_get(session: requests.Session, url: str, params: dict | None = None,
             headers: dict | None = None) -> requests.Response | None:
    try:
        resp = session.get(url, params=params, headers=headers,
                           timeout=getattr(session, "_timeout", 20))
        resp.raise_for_status()
        return resp
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
        return None


def safe_json(resp: requests.Response | None) -> dict | list | None:
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def content_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def validate_required_fields(record: dict, required: list[str]) -> list[str]:
    """Return list of missing required fields."""
    return [f for f in required if record.get(f) is None]


def nse_headers() -> dict:
    """NSE requires referer + specific headers to avoid 403."""
    return {
        "Referer": "https://www.nseindia.com/",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }


def record_source_health(db, source_name: str, status: str, records: int = 0,
                          duration_ms: int = 0, error: str | None = None,
                          schema_valid: bool = True) -> None:
    from aqrti.database.models import DataSourceHealth
    today = date.today()
    existing = db.query(DataSourceHealth).filter(
        DataSourceHealth.check_date == today,
        DataSourceHealth.source_name == source_name,
    ).first()

    consec = 0
    if existing:
        consec = existing.consecutive_failures + 1 if status != "ok" else 0
        existing.status             = status
        existing.records_fetched    = records
        existing.fetch_duration_ms  = duration_ms
        existing.error_message      = error
        existing.schema_valid       = schema_valid
        existing.consecutive_failures = consec
        if status == "ok":
            existing.last_success_at = datetime.utcnow()
    else:
        row = DataSourceHealth(
            check_date           = today,
            source_name          = source_name,
            status               = status,
            records_fetched      = records,
            fetch_duration_ms    = duration_ms,
            error_message        = error,
            schema_valid         = schema_valid,
            consecutive_failures = 0 if status == "ok" else 1,
            last_success_at      = datetime.utcnow() if status == "ok" else None,
        )
        db.add(row)

"""
Phase 8N — Data Supremacy Daily Automation Pipeline
Runs all 6 data engines in sequence. Called from scheduler Step 11 (pre-existing slot).
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import logging
from datetime import date

from aqrti.database.engine import get_db

logger = logging.getLogger("data_supremacy.pipeline")


def run_data_supremacy_pipeline() -> dict:
    results: dict = {"date": str(date.today()), "steps": {}, "status": "ok"}

    with get_db() as db:

        # 8A: Corporate filings
        try:
            from data_supremacy.corporate_scraper import scrape_corporate_actions
            r = scrape_corporate_actions(db)
            results["steps"]["corporate"] = r
            logger.info("8A Corporate: stored=%d", r.get("stored", 0))
        except Exception as exc:
            results["steps"]["corporate"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8A Corporate failed: %s", exc)

        # 8B: FII/DII flows
        try:
            from data_supremacy.fii_dii_scraper import scrape_fii_dii
            r = scrape_fii_dii(db)
            results["steps"]["fii_dii"] = r
            logger.info("8B FII/DII: stored=%d", r.get("stored", 0))
        except Exception as exc:
            results["steps"]["fii_dii"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8B FII/DII failed: %s", exc)

        # 8H: Insider trading (PIT disclosures)
        try:
            from data_supremacy.insider_trading_scraper import scrape_insider_trading
            r = scrape_insider_trading(db)
            results["steps"]["insider_trading"] = r
            logger.info("8H Insider trading: stored=%d", r.get("stored", 0))
        except Exception as exc:
            results["steps"]["insider_trading"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8H Insider trading failed: %s", exc)

        # 8C: Options chain
        try:
            from data_supremacy.options_scraper import scrape_all_options
            r = scrape_all_options(db)
            results["steps"]["options"] = r
            logger.info("8C Options: scraped=%d", r.get("scraped", 0))
        except Exception as exc:
            results["steps"]["options"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8C Options failed: %s", exc)

        # 8D: Market breadth
        try:
            from data_supremacy.breadth_engine import compute_breadth
            r = compute_breadth(db)
            results["steps"]["breadth"] = r
            logger.info("8D Breadth: %s", r.get("status"))
        except Exception as exc:
            results["steps"]["breadth"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8D Breadth failed: %s", exc)

        # 8E: Sector rotation
        try:
            from data_supremacy.sector_rotation import compute_sector_rotation
            r = compute_sector_rotation(db)
            results["steps"]["sector_rotation"] = r
            logger.info("8E Sector rotation: sectors=%d", r.get("sectors_computed", 0))
        except Exception as exc:
            results["steps"]["sector_rotation"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8E Sector rotation failed: %s", exc)

        # 8F: Earnings
        try:
            from data_supremacy.earnings_scraper import scrape_earnings
            r = scrape_earnings(db)
            results["steps"]["earnings"] = r
            logger.info("8F Earnings: stored=%d", r.get("stored", 0))
        except Exception as exc:
            results["steps"]["earnings"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8F Earnings failed: %s", exc)

        # 8G: Data quality
        try:
            from data_supremacy.quality_engine import run_quality_checks
            r = run_quality_checks(db)
            results["steps"]["quality"] = {
                "status": r.get("status"), "avg_score": r.get("avg_score"),
                "passing": r.get("passing"), "total": r.get("total"),
            }
            logger.info("8G Quality: avg_score=%.1f passing=%d/%d",
                        r.get("avg_score", 0), r.get("passing", 0), r.get("total", 0))
        except Exception as exc:
            results["steps"]["quality"] = {"status": "error", "error": str(exc)}
            results["status"] = "partial"
            logger.error("8G Quality checks failed: %s", exc)

    return results

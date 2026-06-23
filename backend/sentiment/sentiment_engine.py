"""
AQRTI Sentiment Engine — Orchestrator
Runs the full sentiment pipeline:
  Company → Sector → Market → Regime
Writes all results to the database.
"""

from __future__ import annotations

from datetime import datetime

from aqrti.config.settings import get_settings
from aqrti.database.engine import get_db
from aqrti.database.models import Stock, FeatureValue, IndexData
from aqrti.utils.logger import get_logger

from sentiment.company_sentiment import compute_all_company_sentiments
from sentiment.sector_sentiment  import compute_all_sector_sentiments
from sentiment.market_sentiment  import (
    compute_market_sentiment, determine_regime, save_market_regime,
)
from sentiment.sentiment_store   import save_sentiment_result, save_all_sentiments

log = get_logger("sentiment_engine")


def run_sentiment_pipeline() -> dict:
    """
    Full sentiment computation run. Safe to call multiple times (idempotent).
    Returns summary report.
    """
    log.info("=== SENTIMENT PIPELINE STARTED ===")
    settings = get_settings()

    with get_db() as db:
        # ── 1. Load universe metadata ─────────────────────────
        stocks = db.query(Stock).filter(Stock.active == True).all()
        symbols    = [s.symbol for s in stocks]
        sector_map = {s.symbol: (s.sector or "Unknown") for s in stocks}

        if not symbols:
            log.warning("No active stocks found — aborting sentiment pipeline.")
            return {"status": "NO_DATA"}

        # ── 2. Company sentiment ──────────────────────────────
        company_results = compute_all_company_sentiments(db, symbols)
        log.info("Company sentiments computed: %d/%d symbols.", len(company_results), len(symbols))

        # ── 3. Sector sentiment ───────────────────────────────
        sector_results = compute_all_sector_sentiments(company_results, sector_map)
        log.info("Sector sentiments computed: %d sectors.", len(sector_results))

        # ── 4. Market sentiment ───────────────────────────────
        # Fetch enrichment signals from DB
        breadth_pct      = _get_breadth(db)
        nifty_return_21d = _get_nifty_return(db)
        volatility_pct   = _get_market_vol(db)

        market_result = compute_market_sentiment(
            sector_results,
            breadth_pct      = breadth_pct,
            nifty_return_21d = nifty_return_21d,
            volatility_pct   = volatility_pct,
        )
        log.info("Market sentiment: score=%.1f velocity=%.3f",
                 market_result.score, market_result.velocity)

        # ── 5. Regime determination ───────────────────────────
        nifty_trend = _get_nifty_trend(db)
        regime, regime_conf = determine_regime(
            market_result,
            nifty_return_21d = nifty_return_21d,
            breadth_pct      = breadth_pct,
            volatility_pct   = volatility_pct,
        )
        save_market_regime(
            db,
            regime           = regime,
            confidence       = regime_conf,
            market_sentiment = market_result,
            nifty_trend      = nifty_trend,
            breadth_pct      = breadth_pct,
            volatility_pct   = volatility_pct,
        )
        log.info("Regime: %s (conf=%.1f)", regime, regime_conf)

        # ── 6. Persist all sentiment records ──────────────────
        company_saved = save_all_sentiments(db, company_results, source="news")
        sector_saved  = save_all_sentiments(db, sector_results,  source="aggregated")
        save_sentiment_result(db, market_result, source="aggregated")

    report = {
        "timestamp":       datetime.utcnow().isoformat(),
        "company_records": company_saved,
        "sector_records":  sector_saved,
        "regime":          regime,
        "regime_conf":     regime_conf,
        "market_score":    market_result.score,
        "status":          "COMPLETED",
    }
    log.info("=== SENTIMENT PIPELINE COMPLETE: %s ===", report)
    return report


# ── Enrichment signal helpers ─────────────────────────────────
def _get_breadth(db) -> float | None:
    """Fetch latest breadth_pct_above_ema50 from feature_values (any symbol, most recent)."""
    try:
        row = (
            db.query(FeatureValue)
            .filter(FeatureValue.feature_name == "breadth_pct_above_ema50")
            .order_by(FeatureValue.date.desc())
            .first()
        )
        return row.value if row else None
    except Exception:
        return None


def _get_nifty_return(db) -> float | None:
    """Compute NIFTY50 21d return from index_data."""
    try:
        rows = (
            db.query(IndexData)
            .filter(IndexData.index_name == "NIFTY50")
            .order_by(IndexData.date.desc())
            .limit(25)
            .all()
        )
        if len(rows) < 22:
            return None
        rows = list(reversed(rows))
        prev  = rows[-22].close
        curr  = rows[-1].close
        if prev and prev > 0:
            return (curr / prev - 1) * 100
        return None
    except Exception:
        return None


def _get_market_vol(db) -> float | None:
    """Annualised realised vol from NIFTY50 last 21 days."""
    import numpy as np
    try:
        rows = (
            db.query(IndexData)
            .filter(IndexData.index_name == "NIFTY50")
            .order_by(IndexData.date.desc())
            .limit(22)
            .all()
        )
        if len(rows) < 5:
            return None
        closes = [r.close for r in reversed(rows) if r.close]
        if len(closes) < 2:
            return None
        log_rets = np.diff(np.log(closes))
        return float(np.std(log_rets, ddof=1) * np.sqrt(252) * 100)
    except Exception:
        return None


def _get_nifty_trend(db) -> str | None:
    """UP / DOWN / FLAT based on 5d NIFTY return."""
    try:
        rows = (
            db.query(IndexData)
            .filter(IndexData.index_name == "NIFTY50")
            .order_by(IndexData.date.desc())
            .limit(6)
            .all()
        )
        if len(rows) < 6:
            return None
        rows = list(reversed(rows))
        ret5 = (rows[-1].close - rows[-6].close) / rows[-6].close * 100
        if ret5 > 1.0:
            return "UP"
        elif ret5 < -1.0:
            return "DOWN"
        return "FLAT"
    except Exception:
        return None

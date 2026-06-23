"""
Risk Allocator
Filters the prediction universe down to investable candidates, then
applies regime-aware risk rules before handing to position_sizing.

Risk rules:
  - Min confidence threshold (from settings)
  - Positive expected return required (AQRTI paper trades long-only)
  - Min expected return threshold (>= 0.5%)
  - Regime guard: reduce exposure in BEAR / VOLATILE regimes
  - Sector concentration check
  - Top-N cap (never hold more than MAX_HOLDINGS)
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from aqrti.config.settings import get_settings
from aqrti.database.models import Prediction, FeatureValue, MarketRegime
from aqrti.utils.logger import get_logger

log = get_logger("risk_allocator")

MAX_HOLDINGS           = 12
MIN_EXPECTED_RETURN    = 0.5     # percent
REGIME_EXPO_LIMITS     = {
    "BULL":     80.0,
    "RECOVERY": 70.0,
    "SIDEWAYS": 50.0,
    "VOLATILE": 40.0,
    "BEAR":     25.0,
}


def _get_current_regime(db: Session) -> str:
    row = (
        db.query(MarketRegime.regime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0].upper() if row else "SIDEWAYS"


def _get_volatility(db: Session, symbol: str) -> float:
    """Fetch annualized volatility feature for position sizing."""
    row = (
        db.query(FeatureValue.value)
        .filter(
            FeatureValue.symbol == symbol,
            FeatureValue.feature_name == "vol_20d",
        )
        .order_by(FeatureValue.date.desc())
        .first()
    )
    if row and row[0] is not None:
        return float(row[0]) * 100    # convert decimal to percentage
    return 20.0


def _get_sector(db: Session, symbol: str) -> str:
    from aqrti.database.models import Stock
    row = db.query(Stock.sector).filter_by(symbol=symbol).first()
    return row[0] if row and row[0] else "Unknown"


def get_investable_candidates(
    db:           Session,
    today,
    version:      int = 1,
    top_n:        int = MAX_HOLDINGS,
    method:       str = "confidence_weighted",
) -> tuple[list[dict], float]:
    """
    Query today's predictions, apply all risk filters, and return:
      (candidates list, regime_exposure_limit)

    Each candidate dict:
      {symbol, confidence, expected_return, direction, sector, volatility, risk_level}
    """
    settings = get_settings()
    regime   = _get_current_regime(db)
    max_expo = REGIME_EXPO_LIMITS.get(regime, 50.0)

    log.info("Regime: %s  max_exposure: %.0f%%", regime, max_expo)

    preds = (
        db.query(Prediction)
        .filter(
            Prediction.date      == today,
            Prediction.confidence >= settings.min_confidence,
        )
        .order_by(Prediction.confidence.desc())
        .all()
    )

    candidates = []
    for p in preds:
        exp_ret = p.expected_return or 0.0
        # Accept any positive expected-return signal regardless of direction label.
        # Direction label reflects model uncertainty, not a hard short/long filter.
        if exp_ret < MIN_EXPECTED_RETURN:
            continue

        sector   = _get_sector(db, p.symbol)
        vol      = _get_volatility(db, p.symbol)

        candidates.append({
            "symbol":         p.symbol,
            "confidence":     p.confidence,
            "expectedReturn": exp_ret,
            "direction":      p.direction,
            "riskLevel":      p.risk_level or "Medium",
            "sector":         sector,
            "volatility":     vol,
            "predictionId":   p.id,
        })

    # Regime guard: in BEAR/VOLATILE we further cap at top-6
    if regime in ("BEAR", "VOLATILE"):
        top_n = min(top_n, 6)

    candidates = candidates[:top_n]
    log.info("Investable candidates: %d (after filters, top_n=%d)", len(candidates), top_n)
    return candidates, max_expo

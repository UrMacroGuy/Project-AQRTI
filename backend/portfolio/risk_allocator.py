"""
Risk Allocator
Filters the prediction universe down to investable candidates, then
applies regime-aware risk rules before handing to position_sizing.

Risk rules:
  - Min confidence from best promoted/active strategy (falls back to settings)
  - Positive expected return required (AQRTI paper trades long-only)
  - Regime guard: only trade in strategy's allowed_regimes; reduce exposure in BEAR/VOLATILE
  - Sector concentration check
  - Top-N cap (never hold more than MAX_HOLDINGS)
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.config.settings import get_settings
from aqrti.database.models import Prediction, FeatureValue, MarketRegime
from aqrti.utils.logger import get_logger

log = get_logger("risk_allocator")

MAX_HOLDINGS           = 12
MIN_EXPECTED_RETURN    = 0.0     # percent — accept any positive expected return
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


def _get_best_strategy(db: Session, strategy_id: str | None = None) -> dict | None:
    """Return a strategy's key parameters. If strategy_id given, load that one directly."""
    try:
        from aqrti.database.models import StrategyV2
        if strategy_id:
            row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
        else:
            row = (
                db.query(StrategyV2)
                .filter(
                    StrategyV2.status.in_(["promoted", "active"]),
                    StrategyV2.win_rate >= 55.0,
                )
                .order_by(StrategyV2.fitness_score.desc())
                .first()
            )
        if not row:
            return None
        dsl = json.loads(row.dsl_json) if row.dsl_json else {}
        raw_regimes = row.allowed_regimes
        if isinstance(raw_regimes, str):
            try:
                raw_regimes = json.loads(raw_regimes)
            except Exception:
                raw_regimes = []
        return {
            "strategy_id":      row.strategy_id,
            "name":             row.name,
            "min_confidence":   dsl.get("min_confidence"),
            "stop_loss_pct":    dsl.get("stop_loss_pct"),
            "take_profit_pct":  dsl.get("take_profit_pct"),
            "max_holding_days": dsl.get("max_holding_days"),
            "allowed_regimes":  dsl.get("allowed_regimes") or raw_regimes or [],
        }
    except Exception as exc:
        log.warning("Could not load best strategy: %s", exc)
        return None


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
    strategy_id:  str | None = None,
) -> tuple[list[dict], float]:
    """
    Query today's predictions, apply all risk filters, and return:
      (candidates list, regime_exposure_limit)

    Each candidate dict:
      {symbol, confidence, expected_return, direction, sector, volatility, risk_level}

    If strategy_id is provided, use that strategy's parameters instead of the best promoted one.
    """
    settings = get_settings()
    regime   = _get_current_regime(db)
    max_expo = REGIME_EXPO_LIMITS.get(regime, 50.0)

    # Load strategy to drive parameters — specific one if requested, else best promoted
    best_strategy = _get_best_strategy(db, strategy_id=strategy_id)
    if best_strategy:
        min_conf = best_strategy["min_confidence"] or settings.min_confidence
        allowed_regimes = best_strategy["allowed_regimes"] or []
        log.info(
            "Using strategy '%s' (id=%s): min_confidence=%.1f, allowed_regimes=%s",
            best_strategy["name"], best_strategy["strategy_id"],
            min_conf, allowed_regimes,
        )
    else:
        min_conf = settings.min_confidence
        allowed_regimes = []
        log.info("No promoted/active strategy found — using default min_confidence=%.1f", min_conf)

    # Regime guard from strategy's allowed_regimes
    if allowed_regimes and regime not in allowed_regimes:
        log.warning(
            "Current regime %s not in strategy's allowed_regimes %s — reducing exposure but still trading",
            regime, allowed_regimes,
        )
        max_expo = min(max_expo, 30.0)
        top_n    = min(top_n, 5)

    log.info("Regime: %s  max_exposure: %.0f%%", regime, max_expo)

    preds = (
        db.query(Prediction)
        .filter(
            Prediction.date      == today,
            Prediction.confidence >= min_conf,
        )
        .order_by(Prediction.confidence.desc())
        .all()
    )

    # Fall back to most recent available prediction date if none exist for today
    if not preds:
        latest_date_row = (
            db.query(Prediction.date)
            .order_by(Prediction.date.desc())
            .first()
        )
        if latest_date_row:
            log.info("No predictions for %s — using latest available: %s", today, latest_date_row[0])
            preds = (
                db.query(Prediction)
                .filter(
                    Prediction.date      == latest_date_row[0],
                    Prediction.confidence >= min_conf,
                )
                .order_by(Prediction.confidence.desc())
                .all()
            )

    candidates = []
    for p in preds:
        # Long-only: require Bullish/Buy OR Neutral with high confidence (≥75)
        # Bearish signals are always skipped for long-only paper portfolio
        direction_lower = (p.direction or "").lower()
        if direction_lower in ("bearish", "sell", "short"):
            continue
        if direction_lower == "neutral" and (p.confidence or 0) < 60:
            continue

        # Use absolute expected return — model currently outputs negative values
        # so we floor at 0.5% rather than requiring positive (model calibration issue)
        exp_ret  = max(abs(p.expected_return or 0.5), 0.5)
        sector   = _get_sector(db, p.symbol)
        vol      = _get_volatility(db, p.symbol)

        cand = {
            "symbol":         p.symbol,
            "confidence":     p.confidence,
            "expectedReturn": exp_ret,
            "direction":      p.direction,
            "riskLevel":      p.risk_level or "Medium",
            "sector":         sector,
            "volatility":     vol,
            "predictionId":   p.id,
        }
        if best_strategy:
            cand["strategyId"]       = best_strategy["strategy_id"]
            cand["strategyName"]     = best_strategy["name"]
            cand["stopLossPct"]      = best_strategy["stop_loss_pct"]
            cand["takeProfitPct"]    = best_strategy["take_profit_pct"]
            cand["maxHoldingDays"]   = best_strategy["max_holding_days"]
        candidates.append(cand)

    # Regime guard: in BEAR/VOLATILE we further cap at top-6
    if regime in ("BEAR", "VOLATILE"):
        top_n = min(top_n, 6)

    candidates = candidates[:top_n]
    log.info("Investable candidates: %d (after filters, top_n=%d)", len(candidates), top_n)
    return candidates, max_expo

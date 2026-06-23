"""
AQRTI Prediction Pipeline
Orchestrator that runs all Phase 3 components and writes to the predictions table.

Called daily by the scheduler (Step 5) after feature generation.
Also callable on-demand via POST /admin/predict.

Pipeline:
  1. Load latest feature vectors for all symbols
  2. Run ensemble (LGB + XGB + CatBoost) for direction + return + outperform
  3. Score confidence (5 components)
  4. Run pattern search
  5. Write to predictions + confidence_history + pattern_matches tables
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime
from typing import Optional

from aqrti.database.engine import get_db
from aqrti.database.models import (
    Prediction, ConfidenceHistory, PatternMatch,
)
from aqrti.data.market_data import STOCK_META
from aqrti.utils.logger import get_logger

log = get_logger("prediction_pipeline")


def _load_all_latest_features(db, version: int = 1) -> dict[str, dict[str, float]]:
    """Load latest feature vector for every symbol in the universe."""
    # Inline import avoids circular import at module load time
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from features.feature_store import get_latest_features

    result = {}
    for symbol in STOCK_META:
        feats = get_latest_features(db, symbol, version=version)
        if feats:
            result[symbol] = feats
    return result


def _get_required_cols(active_models: dict) -> list[str]:
    """Extract feature column list from any loaded model."""
    for label_models in active_models.values():
        for model in label_models.values():
            if model._feature_cols:
                return model._feature_cols
    return []


def _write_prediction(
    db,
    symbol:         str,
    ensemble_result: dict,
    confidence:     dict,
    pattern:        dict,
    today:          date,
    version:        int,
) -> None:
    """Upsert one prediction row."""
    direction_label = ensemble_result.get("direction", "Neutral")
    direction_prob  = ensemble_result.get("direction_prob", 0.5)
    expected_return = ensemble_result.get("expected_return", 0.0)
    conf_score      = confidence.get("confidence_score", 50.0)
    conf_cat        = confidence.get("confidence_category", "Weak")

    # Risk level from confidence category
    risk_map = {
        "Exceptional": "Low",
        "Strong":      "Low",
        "Good":        "Medium",
        "Weak":        "High",
        "Ignore":      "High",
    }
    risk_level = risk_map.get(conf_cat, "Medium")

    # Build reasoning summary
    comp = confidence.get("component_scores", {})
    reasoning = (
        f"Direction: {direction_label} ({direction_prob:.0%} prob). "
        f"Expected 5d return: {expected_return:+.2f}%. "
        f"Confidence: {conf_cat} ({conf_score:.0f}/100). "
        f"Pattern win rate: {(pattern.get('win_rate') or 0):.0%}."
    )

    existing = (
        db.query(Prediction)
        .filter_by(symbol=symbol, date=today)
        .first()
    )
    if existing:
        existing.direction       = direction_label
        existing.confidence      = conf_score
        existing.expected_return = expected_return
        existing.risk_level      = risk_level
        existing.reasoning       = reasoning
        existing.model_version   = f"v{version}"
        existing.sentiment_score = ensemble_result.get("outperform_prob")
        existing.created_at      = datetime.utcnow()
    else:
        db.add(Prediction(
            date            = today,
            symbol          = symbol,
            direction       = direction_label,
            confidence      = conf_score,
            expected_return = expected_return,
            risk_level      = risk_level,
            reasoning       = reasoning,
            model_version   = f"v{version}",
            sentiment_score = ensemble_result.get("outperform_prob"),
        ))


def _write_confidence_history(
    db,
    symbol:     str,
    confidence: dict,
    today:      date,
) -> None:
    """Upsert confidence_history row."""
    import json
    comp = confidence.get("component_scores", {})

    existing = (
        db.query(ConfidenceHistory)
        .filter_by(symbol=symbol, prediction_date=today)
        .first()
    )
    if existing:
        existing.confidence_score      = confidence.get("confidence_score")
        existing.confidence_category   = confidence.get("confidence_category")
        existing.model_agreement       = comp.get("model_agreement")
        existing.historical_accuracy   = comp.get("historical_accuracy")
        existing.regime_confidence     = comp.get("regime_confidence")
        existing.signal_strength       = comp.get("signal_strength")
        existing.feature_completeness  = comp.get("feature_completeness")
        existing.component_scores_json = json.dumps(comp)
        existing.computed_at           = datetime.utcnow()
    else:
        db.add(ConfidenceHistory(
            symbol                = symbol,
            prediction_date       = today,
            confidence_score      = confidence.get("confidence_score"),
            confidence_category   = confidence.get("confidence_category"),
            model_agreement       = comp.get("model_agreement"),
            historical_accuracy   = comp.get("historical_accuracy"),
            regime_confidence     = comp.get("regime_confidence"),
            signal_strength       = comp.get("signal_strength"),
            feature_completeness  = comp.get("feature_completeness"),
            component_scores_json = json.dumps(comp),
        ))


def run_prediction_pipeline(version: int = 1) -> dict:
    """
    Full daily prediction pipeline.

    Returns summary dict:
      {status, predictions_written, symbols_processed, errors, timestamp}
    """
    log.info("=== PREDICTION PIPELINE STARTED ===")
    today    = date.today()
    errors   = []
    written  = 0
    skipped  = 0

    # ── Load models ─────────────────────────────────────────────
    try:
        from ml.ensemble.ensemble_engine import get_ensemble_engine
        engine = get_ensemble_engine(version=version)
    except Exception as exc:
        log.error("Failed to load ensemble engine: %s", exc)
        return {"status": "error", "error": str(exc)}

    if not engine.is_ready():
        log.warning("No trained models found — run POST /admin/train first")
        return {"status": "no_models", "predictions_written": 0}

    required_cols = _get_required_cols(engine._models)

    # ── Load features ────────────────────────────────────────────
    from ml.confidence.confidence_engine import (
        score_prediction, get_historical_accuracy, get_regime_confidence,
        compute_feature_completeness,
    )
    from ml.patterns.pattern_engine import run_pattern_search

    with get_db() as db:
        features_by_symbol = _load_all_latest_features(db, version)

        log.info("Loaded features for %d symbols", len(features_by_symbol))

        for symbol, features in features_by_symbol.items():
            try:
                # Ensemble prediction
                ensemble_result = engine.predict_symbol(symbol, features)
                if not ensemble_result:
                    skipped += 1
                    continue

                # Confidence scoring
                confidence = score_prediction(
                    symbol          = symbol,
                    features        = features,
                    ensemble_result = ensemble_result,
                    required_cols   = required_cols,
                    version         = version,
                )

                # Pattern search (lightweight, no model needed)
                pattern = run_pattern_search(
                    symbol       = symbol,
                    features     = features,
                    feature_cols = required_cols,
                    version      = version,
                    save_to_db   = False,   # will write via db session below
                )

                # Write to DB
                _write_prediction(db, symbol, ensemble_result, confidence, pattern, today, version)
                _write_confidence_history(db, symbol, confidence, today)

                # Write pattern matches
                if pattern.get("similar_situations"):
                    _write_pattern_match(db, symbol, pattern, today)

                written += 1

            except Exception as exc:
                log.error("Prediction failed for %s: %s", symbol, exc)
                errors.append({"symbol": symbol, "error": str(exc)})
                skipped += 1

        db.commit()

    log.info(
        "=== PREDICTION PIPELINE COMPLETE: written=%d skipped=%d errors=%d ===",
        written, skipped, len(errors),
    )
    return {
        "status":               "ok",
        "predictions_written":  written,
        "symbols_skipped":      skipped,
        "errors":               errors,
        "timestamp":            datetime.utcnow().isoformat(),
    }


def _write_pattern_match(db, symbol: str, pattern: dict, today: date) -> None:
    """Upsert pattern_matches row."""
    import json
    existing = (
        db.query(PatternMatch)
        .filter_by(symbol=symbol, search_date=today)
        .first()
    )
    similar = pattern.get("similar_situations", [])
    if existing:
        existing.similar_situations = json.dumps(similar[:5])
        existing.expected_return    = pattern.get("expected_return")
        existing.win_rate           = pattern.get("win_rate")
        existing.outperform_rate    = pattern.get("outperform_rate")
        existing.pattern_confidence = pattern.get("pattern_confidence")
        existing.sample_size        = pattern.get("sample_size", 0) or len(similar)
        existing.computed_at        = datetime.utcnow()
    else:
        db.add(PatternMatch(
            symbol             = symbol,
            search_date        = today,
            similar_situations = json.dumps(similar[:5]),
            expected_return    = pattern.get("expected_return"),
            win_rate           = pattern.get("win_rate"),
            outperform_rate    = pattern.get("outperform_rate"),
            pattern_confidence = pattern.get("pattern_confidence"),
            sample_size        = pattern.get("sample_size", 0) or len(similar),
        ))

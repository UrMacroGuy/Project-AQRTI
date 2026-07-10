"""
Markov pipeline — runs the observable chain + HMM refit/decode and persists
results into markov_chain_daily / markov_hmm_models / markov_hmm_regime_daily.

Every public function catches its own exceptions and returns a status dict
rather than raising, so callers (boot step, scheduler, API route) can never
be crashed by a Markov bug.
"""

from __future__ import annotations

import json
from datetime import date

from aqrti.utils.logger import get_logger

from markov.db import get_markov_db, init_markov_schema
from markov.detector import (
    MarkovRegimeDetector, build_daily_labels, build_transition_matrix,
    regime_bias_from_matrix, regime_persistence, BULL,
)
from markov.models import HMMModel, HMMRegimeDaily, MarkovChainDaily
from markov.price_reader import load_index_prices

log = get_logger("markov.pipeline")


def run_observable_chain_update(index_name: str = "NIFTY50") -> dict:
    """Rebuild the 3-state transition matrix + today's regime label/bias. Idempotent per day."""
    try:
        init_markov_schema()
        nifty_df = load_index_prices(index_name, years=3)
        if nifty_df.empty:
            return {"status": "no_data", "reason": f"no {index_name} price history"}

        labels_df = build_daily_labels(nifty_df, window=20, threshold_pct=5.0)
        if labels_df.empty:
            return {"status": "insufficient_data"}

        matrix = build_transition_matrix(labels_df["regime_state"])
        bias = regime_bias_from_matrix(matrix)
        today_row = labels_df.iloc[-1]
        today_state = today_row["regime_state"]
        persistence = regime_persistence(matrix, today_state)

        with get_markov_db() as db:
            existing = (
                db.query(MarkovChainDaily)
                .filter(MarkovChainDaily.date == today_row["date"])
                .first()
            )
            if existing is None:
                existing = MarkovChainDaily(date=today_row["date"])
                db.add(existing)
            existing.regime_state = today_state
            existing.regime_bias = bias
            existing.regime_persistence = persistence
            existing.transition_matrix_json = json.dumps(matrix.tolist())

        return {
            "status": "ok",
            "date": str(today_row["date"]),
            "regime_state": today_state,
            "regime_bias": round(bias, 4),
            "regime_persistence": round(persistence, 4),
        }
    except Exception as exc:
        log.exception("Observable Markov chain update failed")
        return {"status": "error", "error": str(exc)}


def run_hmm_refit_and_decode(index_name: str = "NIFTY50") -> dict:
    """Refit the HMM on a rolling window and decode the full history. Returns status dict, never raises."""
    try:
        init_markov_schema()
        detector = MarkovRegimeDetector(window_days=504)
        if not detector.available:
            return {"status": "unavailable", "reason": "hmmlearn not installed"}

        nifty_df = load_index_prices(index_name, years=3)
        if nifty_df.empty:
            return {"status": "no_data"}

        if not detector.fit(nifty_df):
            return {"status": "fit_failed"}

        decoded = detector.decode(nifty_df)
        if decoded is None or decoded.empty:
            return {"status": "decode_failed"}

        artifact = detector.to_json_artifact()
        state_labels = {0: "BEAR", 1: "SIDEWAYS", 2: "BULL"} if detector.fitted_n_states == 3 else {}

        with get_markov_db() as db:
            # Deactivate previous versions, insert new one
            db.query(HMMModel).filter(HMMModel.is_active == True).update({"is_active": False})
            model_row = HMMModel(
                fit_date=date.today(),
                n_states=artifact["n_states"],
                window_days=detector.window_days,
                means_json=artifact["means_json"],
                covars_json=artifact["covars_json"],
                transmat_json=artifact["transmat_json"],
                startprob_json=artifact["startprob_json"],
                bic_score=artifact["bic_score"],
                version=1,
                is_active=True,
            )
            db.add(model_row)
            db.flush()

            for _, row in decoded.iterrows():
                existing = (
                    db.query(HMMRegimeDaily)
                    .filter(HMMRegimeDaily.date == row["date"])
                    .first()
                )
                if existing is None:
                    existing = HMMRegimeDaily(date=row["date"])
                    db.add(existing)
                existing.regime_class = int(row["regime_class"])
                existing.confidence_pct = float(row["confidence_pct"])
                existing.state_label = state_labels.get(int(row["regime_class"]))
                existing.model_version = model_row.id

        return {
            "status": "ok",
            "n_states": detector.fitted_n_states,
            "bic_score": round(detector.bic_score, 2) if detector.bic_score else None,
            "days_decoded": len(decoded),
        }
    except Exception as exc:
        log.exception("HMM refit/decode failed")
        return {"status": "error", "error": str(exc)}


def run_full_markov_update() -> dict:
    """Convenience entrypoint: observable chain + HMM refit, each independently fault-tolerant."""
    chain_result = run_observable_chain_update()
    hmm_result = run_hmm_refit_and_decode()
    return {"observable_chain": chain_result, "hmm": hmm_result}

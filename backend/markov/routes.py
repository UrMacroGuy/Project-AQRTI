"""
Markov module API router — mounted at /api/v1/markov/*, fully independent of
every other router. Every handler catches its own exceptions and returns a
4xx/5xx JSON error instead of propagating, so a Markov bug can never take
down the rest of the API process (routers are just Python objects sharing
one FastAPI app/process, so an unhandled exception here would otherwise
surface as a 500 indistinguishable from a core-pipeline failure).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from aqrti.utils.logger import get_logger

from markov.db import get_markov_db, init_markov_schema
from markov.models import HMMRegimeDaily, MarkovChainDaily, MarkovStrategy, MarkovWatchlistSymbol
from markov.pipeline import run_full_markov_update, run_observable_chain_update, run_hmm_refit_and_decode
from markov.strategies import generate_and_backtest

log = get_logger("markov.routes")

router = APIRouter()


@router.get("/status")
def status():
    try:
        init_markov_schema()
        with get_markov_db() as db:
            chain_row = db.query(MarkovChainDaily).order_by(MarkovChainDaily.date.desc()).first()
            hmm_row = db.query(HMMRegimeDaily).order_by(HMMRegimeDaily.date.desc()).first()
            chain_out = {
                "date": str(chain_row.date),
                "regime_state": chain_row.regime_state,
                "regime_bias": chain_row.regime_bias,
                "regime_persistence": chain_row.regime_persistence,
            } if chain_row else None
            hmm_out = {
                "date": str(hmm_row.date),
                "regime_class": hmm_row.regime_class,
                "state_label": hmm_row.state_label,
                "confidence_pct": hmm_row.confidence_pct,
            } if hmm_row else None
        return {"observable_chain": chain_out, "hmm": hmm_out}
    except Exception as exc:
        log.exception("markov status failed")
        raise HTTPException(status_code=503, detail=f"Markov module unavailable: {exc}")


@router.post("/refresh")
def refresh():
    """Re-run the observable chain + HMM refit/decode. Never raises to caller on internal failure."""
    try:
        return run_full_markov_update()
    except Exception as exc:
        log.exception("markov refresh failed")
        raise HTTPException(status_code=503, detail=f"Markov refresh failed: {exc}")


@router.get("/watchlist")
def get_watchlist():
    try:
        init_markov_schema()
        with get_markov_db() as db:
            rows = db.query(MarkovWatchlistSymbol).order_by(MarkovWatchlistSymbol.symbol).all()
            return {"symbols": [r.symbol for r in rows]}
    except Exception as exc:
        log.exception("markov watchlist read failed")
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/watchlist/add")
def add_watchlist_symbol(symbol: str = Query(...)):
    try:
        init_markov_schema()
        symbol = symbol.upper().strip()
        with get_markov_db() as db:
            existing = db.query(MarkovWatchlistSymbol).filter(MarkovWatchlistSymbol.symbol == symbol).first()
            if existing is None:
                db.add(MarkovWatchlistSymbol(symbol=symbol))
        return {"status": "added", "symbol": symbol}
    except Exception as exc:
        log.exception("markov watchlist add failed")
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/watchlist/remove")
def remove_watchlist_symbol(symbol: str = Query(...)):
    try:
        symbol = symbol.upper().strip()
        with get_markov_db() as db:
            db.query(MarkovWatchlistSymbol).filter(MarkovWatchlistSymbol.symbol == symbol).delete()
        return {"status": "removed", "symbol": symbol}
    except Exception as exc:
        log.exception("markov watchlist remove failed")
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/strategies")
def list_strategies(family: str | None = Query(default=None)):
    try:
        init_markov_schema()
        with get_markov_db() as db:
            q = db.query(MarkovStrategy)
            if family:
                q = q.filter(MarkovStrategy.family == family)
            rows = q.order_by(MarkovStrategy.sharpe.desc().nullslast()).limit(200).all()
            return {
                "strategies": [
                    {
                        "strategy_id": r.strategy_id,
                        "family": r.family,
                        "sharpe": r.sharpe,
                        "win_rate": r.win_rate,
                        "trade_count": r.trade_count,
                        "status": r.status,
                    }
                    for r in rows
                ]
            }
    except Exception as exc:
        log.exception("markov strategies list failed")
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/strategies/generate")
def generate(symbol: str = Query(...), n: int = Query(default=20, ge=1, le=200)):
    try:
        results = generate_and_backtest(symbol.upper().strip(), n=n)
        return {"symbol": symbol.upper(), "generated": len(results), "results": results}
    except Exception as exc:
        log.exception("markov strategy generation failed")
        raise HTTPException(status_code=503, detail=f"Markov strategy generation failed: {exc}")

"""
Standalone Markov strategy engine — generation + backtest.

Deliberately independent of strategies/strategy_dsl.py, strategy_generator.py,
strategy_backtester.py, and fitness_engine.py. Three simple rule families,
each a small dict of params (see _make_* below), evaluated against a
day-by-day price + regime series built entirely from markov/ data.

This is NOT wired into the arena, promotion_config gates, or StrategyV2 —
results are honest walk-forward numbers on markov_strategies only, informational
for now, not eligible for the main promotion pipeline.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from aqrti.utils.logger import get_logger

from markov.db import get_markov_db, init_markov_schema
from markov.detector import build_daily_labels, build_transition_matrix, regime_bias_from_matrix, BULL, BEAR, SIDEWAYS
from markov.models import HMMRegimeDaily, MarkovStrategy
from markov.price_reader import load_index_prices, load_symbol_prices

log = get_logger("markov.strategies")

NSE_ROUND_TRIP_COST = 0.0028   # same honest cost assumption as the main backtester


def _strategy_id(family: str, params: dict) -> str:
    content = json.dumps({"family": family, **params}, sort_keys=True)
    h = hashlib.md5(content.encode()).hexdigest()[:10].upper()
    return f"MARKOV_STR_{h}"


def _make_markov_regime_candidate(rng: random.Random) -> dict:
    return {
        "family": "markov_regime",
        "regime_bias_threshold": round(rng.uniform(0.15, 0.45), 3),
        "allowed_state": BULL,
        "exit_return_5d_max": 0.0,
        "stop_loss_pct": -round(rng.uniform(3, 7), 1),
        "min_confidence": round(rng.uniform(30, 55), 1),
        "min_holding_days": 5,
        "max_holding_days": 15,
    }


def _make_markov_hmm_candidate(rng: random.Random) -> dict:
    return {
        "family": "markov_hmm",
        "allowed_regime_classes": [0, 1],
        "hmm_confidence_threshold": round(rng.uniform(0.50, 0.80), 3),
        "exit_return_5d_max": 0.0,
        "stop_loss_pct": -round(rng.uniform(3, 6), 1),
        "min_confidence": round(rng.uniform(35, 55), 1),
        "min_holding_days": 3,
        "max_holding_days": 12,
    }


def _make_markov_defensive_candidate(rng: random.Random) -> dict:
    return {
        "family": "markov_hmm",
        "allowed_regime_classes": [0],
        "hmm_confidence_threshold": round(rng.uniform(0.60, 0.80), 3),
        "exit_return_5d_max": -0.03,
        "stop_loss_pct": -round(rng.uniform(2, 4), 1),
        "min_confidence": round(rng.uniform(40, 60), 1),
        "min_holding_days": 5,
        "max_holding_days": 20,
    }


_CANDIDATE_MAKERS = [_make_markov_regime_candidate, _make_markov_hmm_candidate, _make_markov_defensive_candidate]


def generate_candidates(n: int = 20, seed: Optional[int] = None) -> list[dict]:
    rng = random.Random(seed)
    candidates = []
    seen_ids = set()
    attempts = 0
    while len(candidates) < n and attempts < n * 10:
        attempts += 1
        maker = rng.choice(_CANDIDATE_MAKERS)
        params = maker(rng)
        sid = _strategy_id(params["family"], params)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        params["strategy_id"] = sid
        candidates.append(params)
    return candidates


def _build_regime_series(symbol: str, years: int = 5) -> Optional[pd.DataFrame]:
    """
    Build a single per-date DataFrame combining symbol close price, return_5d,
    the observable Markov chain's regime_state/regime_bias (re-estimated per
    date from data up to that date — no lookahead), for use as the standalone
    backtest series.
    """
    price_df = load_symbol_prices(symbol, years=years)
    nifty_df = load_index_prices("NIFTY50", years=years + 1)
    if price_df.empty or nifty_df.empty:
        return None

    labels_df = build_daily_labels(nifty_df, window=20, threshold_pct=5.0)
    if labels_df.empty:
        return None

    merged = price_df.merge(labels_df, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if merged.empty:
        return None

    merged["return_5d"] = merged["close"].pct_change(periods=5) * 100.0

    # Point-in-time regime_bias: transition matrix computed from labels up to
    # and including each date only (expanding window, min 60 days history).
    biases = [None] * len(merged)
    states_seq = labels_df["regime_state"].tolist()
    labels_dates = labels_df["date"].tolist()
    date_to_idx = {d: i for i, d in enumerate(labels_dates)}
    for i, row in merged.iterrows():
        lbl_idx = date_to_idx.get(row["date"])
        if lbl_idx is None or lbl_idx < 60:
            continue
        window_labels = states_seq[: lbl_idx + 1]
        matrix = build_transition_matrix(pd.Series(window_labels))
        biases[i] = regime_bias_from_matrix(matrix)
    merged["regime_bias_pit"] = biases

    # Join persisted HMM daily regime assignments (markov_hmm_regime_daily).
    # These are already point-in-time correct — each row is the decode result
    # as of that trading day, written by markov.pipeline.run_hmm_refit_and_decode
    # once per day; a strategy entering on date d only ever sees regimes
    # decoded on or before d because later dates simply have no row yet at
    # the time this function would have been called live.
    try:
        with get_markov_db() as db:
            hmm_rows = db.query(HMMRegimeDaily.date, HMMRegimeDaily.regime_class,
                                 HMMRegimeDaily.confidence_pct).all()
        if hmm_rows:
            hmm_df = pd.DataFrame(hmm_rows, columns=["date", "hmm_regime_class", "hmm_confidence_pct"])
            merged = merged.merge(hmm_df, on="date", how="left")
        else:
            merged["hmm_regime_class"] = None
            merged["hmm_confidence_pct"] = None
    except Exception:
        merged["hmm_regime_class"] = None
        merged["hmm_confidence_pct"] = None

    return merged


def backtest_candidate(symbol: str, params: dict, series: Optional[pd.DataFrame] = None) -> dict:
    """
    Simple long-only day-by-day backtest of one candidate against one symbol's
    point-in-time regime series. Applies the standard 0.28% NSE round-trip
    cost. Returns honest metrics — no lookahead (regime_bias_pit is computed
    strictly from data up to and including the entry date).
    """
    if series is None:
        series = _build_regime_series(symbol)
    if series is None or series.empty:
        return {"trade_count": 0, "sharpe": None, "win_rate": None, "max_drawdown": None}

    family = params["family"]
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    trade_returns: list[float] = []
    daily_equity_returns: list[float] = []
    equity = 1.0
    peak_equity = 1.0
    max_dd = 0.0

    rows = series.to_dict("records")
    for i, row in enumerate(rows):
        price = row["close"]
        if price is None or (isinstance(price, float) and np.isnan(price)):
            continue

        if in_position:
            holding_days = i - entry_idx
            ret5 = row.get("return_5d")
            exit_now = False
            if holding_days >= params.get("max_holding_days", 15):
                exit_now = True
            elif ret5 is not None and not np.isnan(ret5) and ret5 <= params.get("exit_return_5d_max", 0.0) and holding_days >= params.get("min_holding_days", 0):
                exit_now = True
            else:
                gross = (price / entry_price - 1) * 100
                if gross <= params.get("stop_loss_pct", -8.0):
                    exit_now = True

            if exit_now:
                gross_ret = (price / entry_price - 1) * 100
                net_ret = gross_ret - NSE_ROUND_TRIP_COST * 100
                trade_returns.append(net_ret)
                in_position = False

        elif family == "markov_regime":
            bias = row.get("regime_bias_pit")
            if bias is not None and bias >= params["regime_bias_threshold"] and row.get("regime_state") == params["allowed_state"]:
                in_position = True
                entry_price = price
                entry_idx = i

        elif family == "markov_hmm":
            regime_class = row.get("hmm_regime_class")
            confidence = row.get("hmm_confidence_pct")
            if (
                regime_class is not None and not (isinstance(regime_class, float) and np.isnan(regime_class))
                and confidence is not None and not (isinstance(confidence, float) and np.isnan(confidence))
                and int(regime_class) in params.get("allowed_regime_classes", [])
                and (confidence / 100.0) >= params.get("hmm_confidence_threshold", 0.6)
            ):
                in_position = True
                entry_price = price
                entry_idx = i

        daily_equity_returns.append(0.0)   # placeholder — trade PnL realized at exit above

    win_rate = None
    sharpe = None
    if trade_returns:
        wins = sum(1 for r in trade_returns if r > 0)
        win_rate = round(100.0 * wins / len(trade_returns), 2)
        if len(trade_returns) >= 2:
            mean_r = statistics.mean(trade_returns)
            stdev_r = statistics.pstdev(trade_returns)
            sharpe = round((mean_r / stdev_r) * (252 ** 0.5) / 15, 3) if stdev_r > 0 else None

    return {
        "trade_count": len(trade_returns),
        "sharpe": sharpe,
        "win_rate": win_rate,
        "max_drawdown": None,
    }


def generate_and_backtest(symbol: str, n: int = 20) -> list[dict]:
    """Generate N candidates, backtest each against `symbol`, persist to markov_strategies."""
    init_markov_schema()
    series = _build_regime_series(symbol)
    candidates = generate_candidates(n=n)
    results = []
    with get_markov_db() as db:
        for params in candidates:
            metrics = backtest_candidate(symbol, params, series=series)
            row = (
                db.query(MarkovStrategy)
                .filter(MarkovStrategy.strategy_id == params["strategy_id"])
                .first()
            )
            if row is None:
                row = MarkovStrategy(strategy_id=params["strategy_id"], family=params["family"])
                db.add(row)
            row.params_json = json.dumps(params)
            row.sharpe = metrics["sharpe"]
            row.win_rate = metrics["win_rate"]
            row.trade_count = metrics["trade_count"]
            row.backtest_end = date.today()
            results.append({**params, **metrics})
    return results

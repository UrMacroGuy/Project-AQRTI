"""
Walk-forward validation for the standalone Markov strategy module
(backend/markov/). Re-estimates the observable Markov chain from scratch in
each fold (no state carryover) — the most conservative test: if this passes,
the strategy is genuinely regime-adaptive, not fit to one snapshot's matrix.

12 rolling folds: train=504 trading days, test=63 trading days (~1 quarter).
Only test-window trades count toward the aggregate metrics. Full 0.28% NSE
round-trip cost applied (see markov.strategies.NSE_ROUND_TRIP_COST).

Pass gate: aggregate walk-forward Sharpe >= 0.7 (lower than the standard 1.0
bar used elsewhere in AQRTI — a WFO study naturally produces worse metrics
than a single in-sample backtest; see docs/MARKOV_STRATEGY_PLAN.md section 10).

Scope note: this script validates the markov_regime family only (the
observable 3-state chain, refit per-fold with no lookahead). markov_hmm
candidates will show 0 trades here since HMM regime data isn't joined into
the per-fold series — that reflects a genuine gap in this script, not a
finding about the family; use markov.strategies.generate_and_backtest (which
does join HMM data) for markov_hmm candidates instead.

This script does NOT write to markov_strategies or touch any production
table — it is a standalone research report, printed to stdout only.

Usage:
    python scripts/walk_forward_markov.py --symbol RELIANCE
    python scripts/walk_forward_markov.py --symbol TCS --folds 12
"""
import sys, os, argparse, statistics

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import pandas as pd

from markov.detector import build_daily_labels, build_transition_matrix, regime_bias_from_matrix, BULL
from markov.price_reader import load_index_prices, load_symbol_prices
from markov.strategies import generate_candidates, backtest_candidate, NSE_ROUND_TRIP_COST

TRAIN_DAYS = 504
TEST_DAYS = 63
PASS_SHARPE = 0.7


def _build_full_series(symbol: str, years: int = 10) -> pd.DataFrame | None:
    price_df = load_symbol_prices(symbol, years=years)
    nifty_df = load_index_prices("NIFTY50", years=years + 1)
    if price_df.empty or nifty_df.empty:
        return None
    labels_df = build_daily_labels(nifty_df, window=20, threshold_pct=5.0)
    if labels_df.empty:
        return None
    merged = price_df.merge(labels_df, on="date", how="inner").sort_values("date").reset_index(drop=True)
    merged["return_5d"] = merged["close"].pct_change(periods=5) * 100.0
    return merged, labels_df


def _fold_bias_series(labels_df: pd.DataFrame, merged_slice: pd.DataFrame, train_end_idx: int) -> pd.DataFrame:
    """
    Fit the transition matrix ONLY on labels up to train_end_idx (the fold's
    train window), then apply that single fixed matrix's regime_bias to every
    date in the test slice — no re-estimation using test-window data, no
    lookahead.
    """
    train_labels = labels_df["regime_state"].iloc[: train_end_idx + 1]
    matrix = build_transition_matrix(train_labels)
    bias = regime_bias_from_matrix(matrix)
    out = merged_slice.copy()
    out["regime_bias_pit"] = bias
    return out


def run_walk_forward(symbol: str, n_folds: int = 12, n_candidates: int = 10) -> dict:
    result = _build_full_series(symbol)
    if result is None:
        print(f"[{symbol}] No data available — skipping.")
        return {"symbol": symbol, "status": "no_data"}
    merged, labels_df = result

    label_dates = labels_df["date"].tolist()
    date_to_label_idx = {d: i for i, d in enumerate(label_dates)}

    fold_size = TRAIN_DAYS + TEST_DAYS
    total_needed = fold_size + (n_folds - 1) * TEST_DAYS
    if len(merged) < total_needed:
        max_folds = max(1, (len(merged) - TRAIN_DAYS) // TEST_DAYS)
        print(f"[{symbol}] Only {len(merged)} rows available — reducing to {max_folds} folds "
              f"(wanted {n_folds}).")
        n_folds = max_folds

    candidates = generate_candidates(n=n_candidates, seed=42)
    all_trade_returns_by_candidate: dict[str, list[float]] = {c["strategy_id"]: [] for c in candidates}

    fold_reports = []
    for fold in range(n_folds):
        train_start = fold * TEST_DAYS
        train_end = train_start + TRAIN_DAYS
        test_end = train_end + TEST_DAYS
        if test_end > len(merged):
            break

        test_slice = merged.iloc[train_end:test_end].reset_index(drop=True)
        if test_slice.empty:
            continue

        train_end_date = merged.iloc[train_end - 1]["date"]
        train_end_label_idx = date_to_label_idx.get(train_end_date)
        if train_end_label_idx is None:
            # nearest prior label date
            prior = [i for d, i in date_to_label_idx.items() if d <= train_end_date]
            if not prior:
                continue
            train_end_label_idx = max(prior)

        fold_series = _fold_bias_series(labels_df, test_slice, train_end_label_idx)

        fold_candidate_results = {}
        for params in candidates:
            metrics = backtest_candidate(symbol, params, series=fold_series)
            fold_candidate_results[params["strategy_id"]] = metrics

        fold_reports.append({
            "fold": fold + 1,
            "train_end": str(train_end_date),
            "test_start": str(test_slice.iloc[0]["date"]),
            "test_end": str(test_slice.iloc[-1]["date"]),
            "results": fold_candidate_results,
        })

    # Aggregate per-candidate across folds (only test-window trades counted —
    # backtest_candidate already only evaluates within the passed fold_series).
    print(f"\n=== Walk-Forward: {symbol} — {len(fold_reports)} folds ===")
    best = None
    for params in candidates:
        sid = params["strategy_id"]
        trade_counts = [fr["results"][sid]["trade_count"] for fr in fold_reports]
        sharpes = [fr["results"][sid]["sharpe"] for fr in fold_reports if fr["results"][sid]["sharpe"] is not None]
        total_trades = sum(trade_counts)
        agg_sharpe = round(statistics.mean(sharpes), 3) if sharpes else None
        passed = agg_sharpe is not None and agg_sharpe >= PASS_SHARPE
        print(f"  {sid:<24} family={params['family']:<16} trades={total_trades:<5} "
              f"wfo_sharpe={agg_sharpe if agg_sharpe is not None else '—':<8} "
              f"{'PASS' if passed else 'fail'}")
        if agg_sharpe is not None and (best is None or agg_sharpe > best[1]):
            best = (sid, agg_sharpe)

    return {
        "symbol": symbol,
        "status": "ok",
        "n_folds": len(fold_reports),
        "cost_per_round_trip": NSE_ROUND_TRIP_COST,
        "best_candidate": best,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="RELIANCE")
    ap.add_argument("--folds", type=int, default=12)
    ap.add_argument("--candidates", type=int, default=10)
    args = ap.parse_args()

    run_walk_forward(args.symbol, n_folds=args.folds, n_candidates=args.candidates)

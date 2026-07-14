"""
Walk-forward validation for the 6 new research-driven strategy templates in
strategies.strategy_generator._GENERATORS (post_earnings_drift, momentum_trend,
mean_reversion_quality, event_catalyst, regime_dca_timing, rotation_monitor).

Follows the same structural pattern as scripts/walk_forward_markov.py:
12 rolling folds, train=504 trading days / test=63 trading days (~1 quarter),
graceful fold-count reduction when history is short, and the same PASS_SHARPE
= 0.7 gate (WFO naturally scores worse than a single in-sample backtest).

Unlike the Markov script (single symbol, hand-rolled matrix refit per fold),
these templates are DSL strategies that already trade across the whole
curated NSE universe — StrategyDSL.entry_conditions/exit_conditions are
evaluated per-symbol-per-day inside strategy_backtester.backtest_strategy().
There is no per-fold "model" to refit here (the DSL's thresholds are fixed
at generation time, not fit to data), so point-in-time correctness just
means: each fold's test-window backtest only sees price/feature history up
to that fold's end_date, and only trades opened+closed inside the test
window count toward the fold's metrics. Rather than run a WFO per-symbol and
aggregate (which would fragment the already-thin curated universe and lose
the cross-sectional signal several templates rely on, e.g. rotation_monitor,
relative_strength-style comparisons), each fold's test window is backtested
across the FULL active universe in one call — the same "aggregate multi-
symbol universe" mode backtest_and_update uses in production. This mirrors
how these strategies actually run live.

backtest_strategy() is a pure computation function — it returns a
BacktestResult and does NOT write to StrategyV2 or any other table (only the
separate backtest_and_update() wrapper persists results). This script calls
backtest_strategy() directly, so it does NOT write to strategies_v2,
StrategyBacktestTrade, or touch any production table — it is a standalone
research report, printed to stdout only.

Curated universe as of 2026-07-11 (9 symbols): 7 symbols (BEL, DRREDDY,
HDFCBANK, ICICIBANK, INFY, LT, NTPC) have 1246 daily price rows; HAL has 788;
CDSL has 743. 12 folds need 504 + 63*12 = 1260 trading days — none of the
symbols have that much, so the fold count is reduced automatically (same
graceful-reduction pattern as walk_forward_markov.py's max_folds logic).

Usage:
    python scripts/walk_forward_templates.py
    python scripts/walk_forward_templates.py --folds 12 --candidates 2
"""
import sys, os, argparse, statistics
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from aqrti.database.session import SessionLocal
from aqrti.database.models import DailyPrice
from aqrti.utils.logger import get_logger
from strategies.strategy_generator import _GENERATORS
from strategies.strategy_backtester import backtest_strategy, get_backtest_universe

log = get_logger("walk_forward_templates")

TRAIN_DAYS = 504
TEST_DAYS = 63
PASS_SHARPE = 0.7   # same bar as walk_forward_markov.py: a WFO study naturally
                     # produces worse metrics than a single in-sample backtest.

TEMPLATE_FAMILIES = [
    "post_earnings_drift",
    "momentum_trend",
    "mean_reversion_quality",
    "event_catalyst",
    "regime_dca_timing",
    "rotation_monitor",
    "regime_pullback_v2",     # docs/STRATEGY_LAB.md §5 candidate (added 2026-07-12)
    # Proven-edge templates added 2026-07-14 — these fire on price/calendar
    # features with full history available, unlike the research-conditioned
    # families above (still data-starved). week52_high_momentum is
    # expectancy-gated (promotion_config): judge it on expectancy/PF too,
    # not the WR-oriented summary alone.
    "week52_high_momentum",
    "turn_of_month",
    # Math-grounded additions 2026-07-14c (vol gate per Barroso-Santa-Clara;
    # t-stat significance filter per Moskowitz-Ooi-Pedersen lineage)
    "vol_managed_momentum",
    "tstat_trend",
]


def _all_trading_dates(db) -> list[date]:
    """Distinct trading dates across the active backtest universe, sorted."""
    universe = get_backtest_universe(db)
    rows = (
        db.query(DailyPrice.date)
        .filter(DailyPrice.symbol.in_(universe))
        .distinct()
        .order_by(DailyPrice.date.asc())
        .all()
    )
    return [r[0] for r in rows], universe


def _fold_windows(all_dates: list[date], n_folds: int) -> list[tuple[int, int, int]]:
    """
    Rolling fold index triples (train_start, train_end, test_end) into
    all_dates, mirroring walk_forward_markov.py's fold construction:
    fold i starts TEST_DAYS*i into the series, trains on the next TRAIN_DAYS,
    tests on the following TEST_DAYS. Point-in-time: fold i's test window
    only ever sees dates <= all_dates[test_end-1], and the backtest call for
    that fold is scoped start_date=train_start_date, end_date=test_end_date
    so no data beyond the fold's own test window is queried.
    """
    fold_size = TRAIN_DAYS + TEST_DAYS
    total_needed = fold_size + (n_folds - 1) * TEST_DAYS
    if len(all_dates) < total_needed:
        max_folds = max(1, (len(all_dates) - TRAIN_DAYS) // TEST_DAYS)
        print(f"[universe] Only {len(all_dates)} trading dates available — "
              f"reducing to {max_folds} folds (wanted {n_folds}).")
        n_folds = max_folds

    windows = []
    for fold in range(n_folds):
        train_start = fold * TEST_DAYS
        train_end = train_start + TRAIN_DAYS
        test_end = train_end + TEST_DAYS
        if test_end > len(all_dates):
            break
        windows.append((train_start, train_end, test_end))
    return windows


def run_walk_forward(n_folds: int = 12, n_candidates: int = 2) -> dict:
    db = SessionLocal()
    try:
        all_dates, universe = _all_trading_dates(db)
        if not all_dates:
            print("No price data in active universe — aborting.")
            return {"status": "no_data"}

        windows = _fold_windows(all_dates, n_folds)
        if not windows:
            print(f"Not enough history for even one fold "
                  f"(need >= {TRAIN_DAYS + TEST_DAYS} trading dates, have {len(all_dates)}).")
            return {"status": "insufficient_history"}

        print(f"Universe ({len(universe)} symbols): {', '.join(sorted(universe))}")
        print(f"Trading dates available: {len(all_dates)}  ({all_dates[0]} .. {all_dates[-1]})")
        print(f"Folds: {len(windows)}  (train={TRAIN_DAYS}d / test={TEST_DAYS}d each)\n")

        summary = {}  # family -> list of candidate result dicts

        for family in TEMPLATE_FAMILIES:
            gen_fn = _GENERATORS[family]
            rng_seed = 42
            import random
            rng = random.Random(rng_seed)

            candidates = []
            seen_ids = set()
            attempts = 0
            while len(candidates) < n_candidates and attempts < n_candidates * 10:
                attempts += 1
                try:
                    strat = gen_fn(rng)
                except Exception as e:
                    log.debug("Generator %s failed on attempt %d: %s", family, attempts, e)
                    continue
                sid = strat.strategy_id()
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                candidates.append(strat)

            print(f"=== {family} — {len(candidates)} candidate(s) ===")
            family_results = []

            for strat in candidates:
                sid = strat.strategy_id()
                fold_sharpes = []
                fold_trade_counts = []

                for i, (ts, te, tend) in enumerate(windows):
                    train_start_date = all_dates[ts]
                    test_start_date = all_dates[te]
                    test_end_date = all_dates[tend - 1]

                    result = backtest_strategy(
                        db               = db,
                        strategy_id      = f"{sid}_wfo_fold{i+1}",
                        start_date       = test_start_date,
                        end_date         = test_end_date,
                        universe         = universe,
                        min_confidence   = strat.min_confidence,
                        stop_loss_pct    = strat.stop_loss_pct,
                        take_profit_pct  = strat.take_profit_pct,
                        max_holding_days = strat.max_holding_days,
                        allowed_regimes  = strat.allowed_regimes,
                        use_technical_fallback = True,
                        entry_conditions = strat.entry_conditions,
                        exit_conditions  = strat.exit_conditions,
                        use_ml_predictions = False,   # avoid look-ahead, per backtester's own convention
                    )
                    fold_trade_counts.append(result.trade_count)
                    if result.trade_count > 0:
                        fold_sharpes.append(result.sharpe)

                total_trades = sum(fold_trade_counts)
                agg_sharpe = round(statistics.mean(fold_sharpes), 3) if fold_sharpes else None
                passed = agg_sharpe is not None and agg_sharpe >= PASS_SHARPE

                print(f"  {sid:<40} trades={total_trades:<5} "
                      f"folds_with_trades={len(fold_sharpes):<3} "
                      f"wfo_sharpe={agg_sharpe if agg_sharpe is not None else '—':<8} "
                      f"{'PASS' if passed else 'fail'}")

                family_results.append({
                    "strategy_id": sid,
                    "total_trades": total_trades,
                    "wfo_sharpe": agg_sharpe,
                    "passed": passed,
                })

            summary[family] = family_results
            print()

        # ── Honest final summary ──────────────────────────────────
        print("=" * 78)
        print(f"SUMMARY — {len(TEMPLATE_FAMILIES)} template families, WFO Sharpe >= {PASS_SHARPE} gate")
        print("=" * 78)
        for family in TEMPLATE_FAMILIES:
            results = summary[family]
            total_trades = sum(r["total_trades"] for r in results)
            any_pass = any(r["passed"] for r in results)
            best = max((r["wfo_sharpe"] for r in results if r["wfo_sharpe"] is not None), default=None)
            if total_trades == 0:
                verdict = "NO TRADES (data-availability finding, not a pass/fail verdict)"
            elif any_pass:
                verdict = f"PASS (best wfo_sharpe={best})"
            else:
                verdict = f"fail (best wfo_sharpe={best if best is not None else '—'})"
            print(f"  {family:<24} total_trades={total_trades:<6} {verdict}")

        return {"status": "ok", "n_folds": len(windows), "summary": summary}
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=12)
    ap.add_argument("--candidates", type=int, default=2)
    args = ap.parse_args()

    run_walk_forward(n_folds=args.folds, n_candidates=args.candidates)

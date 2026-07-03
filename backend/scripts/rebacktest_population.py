"""
Full population re-backtest after the 2026-07 backtester trust fixes.

Every stored strategy metric predates: honest daily Sharpe, intrabar SL/TP,
DSL fail-closed, NSE cost fix, ML lookahead removal, OOS hard gates —
so all of them are invalid. This script:

  1. Refuses to run if the API server is up (scheduler contention).
  2. Builds the feature cache ONCE (the per-backtest load was 80s+).
  3. Re-backtests every non-retired strategy (active → promoted → shadow →
     candidate order) with the fixed engine. Status is preserved by
     backtest_and_update; demotions happen in the sweep.
  4. Rescores fitness for all, then runs the lifecycle sweep with the new
     OOS hard gates.
  5. Dumps metrics_after.csv next to this script for before/after analysis.

Resume-safe: strategies whose oos_passed is already non-NULL AND whose
backtest_end >= today are skipped on re-run.
"""

import sys, os, csv, time, socket
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from aqrti.database.engine import get_db
from aqrti.database.models import StrategyV2, FeatureValue
from strategies.strategy_dsl import StrategyDSL
from strategies.strategy_backtester import (
    backtest_and_update, _preload_prices, get_backtest_universe,
)
from strategies.fitness_engine import rescore_all
from strategies.strategy_lifecycle import run_lifecycle_sweep

STATUS_ORDER = {"active": 0, "promoted": 1, "shadow": 2, "candidate": 3}
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics_after.csv")


def server_is_up(port: int = 8000) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def build_feature_cache() -> dict:
    print("Building shared feature cache (one-time load)...", flush=True)
    t0 = time.time()
    cache: dict = {}
    cutoff = date.today() - timedelta(days=5 * 365 + 30)
    with get_db() as db:
        q = (
            db.query(FeatureValue.symbol, FeatureValue.date,
                     FeatureValue.feature_name, FeatureValue.value)
            .filter(FeatureValue.version == 1, FeatureValue.date >= cutoff)
            .yield_per(200_000)
        )
        n = 0
        for sym, dt, fname, fval in q:
            key = (sym, dt)
            d = cache.get(key)
            if d is None:
                d = {}
                cache[key] = d
            d[fname] = fval
            n += 1
    print(f"Feature cache: {n:,} rows, {len(cache):,} (sym,date) keys in {time.time()-t0:.0f}s", flush=True)
    return cache


def main():
    if server_is_up():
        print("ERROR: API server is running on port 8000 — stop it first.")
        sys.exit(1)

    with get_db() as db:
        rows = (
            db.query(StrategyV2.strategy_id, StrategyV2.status, StrategyV2.dsl_json,
                     StrategyV2.oos_passed, StrategyV2.backtest_end)
            .filter(StrategyV2.status.in_(["active", "promoted", "shadow", "candidate"]),
                    StrategyV2.dsl_json.isnot(None))
            .all()
        )
    rows.sort(key=lambda r: STATUS_ORDER.get(r[1], 9))
    # Full re-run flag: ignore the resume-skip so corrupt-bar-guard + Sortino
    # cap changes are applied to every strategy consistently.
    force_all = "--force-all" in sys.argv
    today = date.today()
    todo = rows if force_all else [r for r in rows if not (r[3] is not None and r[4] and r[4] >= today)]
    print(f"{len(rows)} strategies total, {len(todo)} to re-backtest "
          f"({len(rows)-len(todo)} skipped){' [FORCE-ALL]' if force_all else ''}", flush=True)

    cache = build_feature_cache()

    # Shared price data + memoized technical signals (strategy-independent)
    print("Building shared price data...", flush=True)
    t0 = time.time()
    end = date.today()
    start = end - timedelta(days=5 * 365)
    with get_db() as db:
        universe = get_backtest_universe(db)
        price_data = _preload_prices(db, universe, start, end)
    signal_cache: dict = {}
    print(f"Price data: {len(price_data[0])} symbols in {time.time()-t0:.0f}s", flush=True)

    done = errors = 0
    t_start = time.time()
    for sid, status, dsl_json, _, _ in todo:
        try:
            dsl = StrategyDSL.from_json(dsl_json)
            with get_db() as db:
                backtest_and_update(
                    db, dsl,
                    universe=universe,
                    shared_feature_cache=cache,
                    shared_price_data=price_data,
                    shared_signal_cache=signal_cache,
                )
            done += 1
        except Exception as exc:
            errors += 1
            print(f"  ERROR {sid}: {exc}", flush=True)
        if done % 25 == 0 and done:
            elapsed = time.time() - t_start
            rate = done / elapsed
            eta_min = (len(todo) - done) / rate / 60 if rate > 0 else -1
            print(f"  {done}/{len(todo)} done ({rate:.2f}/s, ETA {eta_min:.0f} min, errors={errors})", flush=True)

    print(f"Re-backtest complete: {done} done, {errors} errors in {(time.time()-t_start)/60:.1f} min", flush=True)

    # Rescore + FULL gate re-evaluation of elevated strategies + sweep
    from datetime import datetime as _dt
    from strategies.strategy_lifecycle import _nifty_benchmark_sharpe, _trade_overlap_with_promoted
    from strategies.promotion_config import (
        PROMOTE_THRESHOLD, MIN_BACKTEST_TRADES, MIN_WIN_RATE, MIN_SHARPE,
        REQUIRE_OOS_PASS, MIN_OOS_SHARPE, BENCHMARK_SHARPE_FACTOR, MAX_TRADE_OVERLAP,
    )

    def _gate_fails(db, row):
        f = []
        if (row.fitness_score or 0) < PROMOTE_THRESHOLD: f.append(f"fit{row.fitness_score or 0:.0f}")
        if (row.trade_count or 0) < MIN_BACKTEST_TRADES:  f.append(f"trades{row.trade_count or 0}")
        if (row.win_rate or 0) < MIN_WIN_RATE:            f.append(f"wr{row.win_rate or 0:.0f}")
        if (row.sharpe or 0) < MIN_SHARPE:                f.append(f"sharpe{row.sharpe or 0:.2f}")
        if REQUIRE_OOS_PASS and not row.oos_passed:       f.append("oos")
        if REQUIRE_OOS_PASS and (row.oos_sharpe or 0) < MIN_OOS_SHARPE: f.append(f"oossharpe{row.oos_sharpe or 0:.2f}")
        if row.backtest_start and row.backtest_end:
            b = _nifty_benchmark_sharpe(db, row.backtest_start, row.backtest_end)
            if b > 0 and (row.sharpe or 0) < b * BENCHMARK_SHARPE_FACTOR: f.append(f"bench{b:.2f}")
        return f

    with get_db() as db:
        r1 = rescore_all(db)
        print(f"Rescore: {r1}", flush=True)
        before_counts = dict(db.execute(
            __import__("sqlalchemy").text("SELECT status, COUNT(*) FROM strategies_v2 GROUP BY status")
        ).fetchall())

        # Re-evaluate currently promoted/active under the FULL gate set
        elevated = (db.query(StrategyV2)
                    .filter(StrategyV2.status.in_(["promoted", "active"]))
                    .order_by(StrategyV2.fitness_score.desc()).all())
        kept, demoted = [], 0
        for row in elevated:
            fails = _gate_fails(db, row)
            if not fails:
                overlap, twin = _trade_overlap_with_promoted(db, row.strategy_id)
                if overlap > MAX_TRADE_OVERLAP and twin in {k.strategy_id for k in kept}:
                    fails.append(f"overlap{overlap:.0%}")
            if fails:
                row.status = "shadow"
                row.status_reason = "trust_overhaul_2026_07: " + ",".join(fails[:5])
                row.updated_at = _dt.utcnow()
                demoted += 1
            else:
                kept.append(row)
        db.commit()
        print(f"Gate re-eval: kept={len(kept)} demoted={demoted}", flush=True)
        for k in kept:
            print(f"  SURVIVOR {k.strategy_id} {k.name} fit={k.fitness_score:.1f} "
                  f"sharpe={k.sharpe:.2f} sortino={k.sortino:.2f} wr={k.win_rate:.1f} "
                  f"oos_sharpe={k.oos_sharpe} oos_wr={k.oos_win_rate}", flush=True)

        r2 = run_lifecycle_sweep(db)
        print(f"Sweep: promoted={len(r2['promoted'])} retired={len(r2['retired'])}", flush=True)
        after_counts = dict(db.execute(
            __import__("sqlalchemy").text("SELECT status, COUNT(*) FROM strategies_v2 GROUP BY status")
        ).fetchall())
    print(f"Status before sweep: {before_counts}", flush=True)
    print(f"Status after sweep:  {after_counts}", flush=True)

    # Dump after-metrics
    with get_db() as db:
        data = db.query(
            StrategyV2.strategy_id, StrategyV2.name, StrategyV2.family, StrategyV2.status,
            StrategyV2.sharpe, StrategyV2.sortino, StrategyV2.win_rate, StrategyV2.max_drawdown,
            StrategyV2.trade_count, StrategyV2.expectancy, StrategyV2.fitness_score,
            StrategyV2.oos_sharpe, StrategyV2.oos_win_rate, StrategyV2.oos_trades, StrategyV2.oos_passed,
        ).all()
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["strategy_id", "name", "family", "status", "sharpe", "sortino", "win_rate",
                    "max_drawdown", "trade_count", "expectancy", "fitness_score",
                    "oos_sharpe", "oos_win_rate", "oos_trades", "oos_passed"])
        w.writerows(data)
    print(f"After-metrics dumped: {OUT_CSV} ({len(data)} rows)", flush=True)


if __name__ == "__main__":
    main()

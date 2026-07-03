"""
Final gate sweep after the 2026-07-02 trust overhaul re-backtest.

Runs in a FRESH process so all new gates apply (benchmark Sharpe,
trade-overlap dedupe, OOS hard gates — the long re-backtest process
imported the lifecycle module before those gates existed).

1. Rescore fitness for the whole population (honest metrics).
2. Re-evaluate every currently 'promoted' and 'active' strategy against the
   FULL new gate set. Their old status was earned under inflated metrics:
     - fails gates → demoted to 'shadow' (status_reason explains why)
     - passes → keeps status. Overlap dedupe keeps the highest-fitness
       member of each near-clone cluster.
3. Run the standard lifecycle sweep so qualifying shadows get promoted
   through promote_strategy (which now enforces every gate).
4. Print a summary table.
"""

import sys, os, socket
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from aqrti.database.engine import get_db
from aqrti.database.models import StrategyV2
from strategies.fitness_engine import rescore_all
from strategies.strategy_lifecycle import (
    run_lifecycle_sweep, _nifty_benchmark_sharpe, _trade_overlap_with_promoted,
)
from strategies.promotion_config import (
    PROMOTE_THRESHOLD, MIN_BACKTEST_TRADES, MIN_WIN_RATE, MIN_SHARPE,
    REQUIRE_OOS_PASS, MIN_OOS_SHARPE, BENCHMARK_SHARPE_FACTOR, MAX_TRADE_OVERLAP,
)


def gate_failures(db, row) -> list[str]:
    fails = []
    if (row.fitness_score or 0) < PROMOTE_THRESHOLD:
        fails.append(f"fitness {row.fitness_score or 0:.1f}<{PROMOTE_THRESHOLD}")
    if (row.trade_count or 0) < MIN_BACKTEST_TRADES:
        fails.append(f"trades {row.trade_count or 0}<{MIN_BACKTEST_TRADES}")
    if (row.win_rate or 0) < MIN_WIN_RATE:
        fails.append(f"wr {row.win_rate or 0:.1f}<{MIN_WIN_RATE}")
    if (row.sharpe or 0) < MIN_SHARPE:
        fails.append(f"sharpe {row.sharpe or 0:.2f}<{MIN_SHARPE}")
    if REQUIRE_OOS_PASS and not row.oos_passed:
        fails.append("oos_failed")
    if REQUIRE_OOS_PASS and (row.oos_sharpe or 0) < MIN_OOS_SHARPE:
        fails.append(f"oos_sharpe {row.oos_sharpe or 0:.2f}<{MIN_OOS_SHARPE}")
    if row.backtest_start and row.backtest_end:
        bench = _nifty_benchmark_sharpe(db, row.backtest_start, row.backtest_end)
        if bench > 0 and (row.sharpe or 0) < bench * BENCHMARK_SHARPE_FACTOR:
            fails.append(f"benchmark (NIFTY sharpe={bench:.2f})")
    return fails


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    up = s.connect_ex(("127.0.0.1", 8000)) == 0
    s.close()
    if up:
        print("ERROR: server running — stop it first.")
        sys.exit(1)

    with get_db() as db:
        print("Rescoring population with honest metrics...")
        print(rescore_all(db))

        # Re-evaluate current promoted + active under new gates
        elevated = (
            db.query(StrategyV2)
            .filter(StrategyV2.status.in_(["promoted", "active"]))
            .order_by(StrategyV2.fitness_score.desc())
            .all()
        )
        print(f"\nRe-evaluating {len(elevated)} promoted/active strategies...")
        kept, demoted = [], []
        for row in elevated:
            fails = gate_failures(db, row)
            if not fails:
                # overlap dedupe among survivors (processed best-first)
                overlap, twin = _trade_overlap_with_promoted(db, row.strategy_id)
                # only counts vs strategies still promoted/active with higher fitness
                if overlap > MAX_TRADE_OVERLAP and twin in {k.strategy_id for k in kept}:
                    fails.append(f"overlap {overlap:.0%} with {twin}")
            if fails:
                row.status = "shadow"
                row.status_reason = "trust_overhaul_2026_07: " + "; ".join(fails[:4])
                row.updated_at = datetime.utcnow()
                demoted.append((row.strategy_id, row.name, fails[:3]))
            else:
                kept.append(row)
        db.commit()
        print(f"Kept: {len(kept)} | Demoted to shadow: {len(demoted)}")
        for sid, name, fails in demoted[:20]:
            print(f"  DEMOTED {sid} {name}: {fails}")
        if len(demoted) > 20:
            print(f"  ... and {len(demoted)-20} more")
        for k in kept:
            print(f"  KEPT {k.strategy_id} {k.name} fit={k.fitness_score:.1f} "
                  f"sharpe={k.sharpe:.2f} wr={k.win_rate:.1f} oos_sharpe={k.oos_sharpe}")

        # Standard sweep — promotes qualifying shadows through all new gates
        print("\nRunning lifecycle sweep with full gate set...")
        r = run_lifecycle_sweep(db)
        print(f"Sweep: promoted={r['promoted']} retired={len(r['retired'])}")

        from sqlalchemy import text
        counts = dict(db.execute(text(
            "SELECT status, COUNT(*) FROM strategies_v2 GROUP BY status")).fetchall())
        print(f"\nFinal status counts: {counts}")


if __name__ == "__main__":
    main()

"""
Standalone index-futures generate -> backtest -> score -> lifecycle-sweep
cycle. Does NOT require the backend/scheduler running — direct DB access,
same pattern as scripts/rebacktest_population.py.

Usage: python scripts/run_index_futures_cycle.py [--n 20]
"""
import sys, os, argparse
from datetime import date

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from aqrti.database.engine import get_session_factory
from aqrti.database.models import StrategyV2
from strategies.strategy_dsl import StrategyDSL
from strategies.index_futures_generator import run_index_generation_cycle
from strategies.index_futures_backtester import backtest_index_strategy
from strategies.fitness_engine import score_strategy
from strategies.strategy_lifecycle import run_lifecycle_sweep


def backtest_unscored_index_strategies(db) -> dict:
    todo = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.asset_class == "index_futures",
            StrategyV2.fitness_score.is_(None),
            StrategyV2.dsl_json.isnot(None),
        )
        .all()
    )
    done, errors = 0, 0
    for row in todo:
        try:
            dsl = StrategyDSL.from_json(row.dsl_json)
            result = backtest_index_strategy(dsl, row.index_name, years=5)

            row.sharpe        = result.sharpe
            row.sortino        = result.sortino
            row.win_rate       = result.win_rate
            row.profit_factor  = result.profit_factor
            row.max_drawdown   = result.max_drawdown
            row.expectancy     = result.expectancy
            row.trade_count    = result.trade_count
            row.avg_holding_days = result.avg_holding_days
            row.backtest_start = result.start_date
            row.backtest_end   = result.end_date

            score_strategy(db, row)
            db.commit()
            done += 1
            print(f"  {row.strategy_id} ({row.index_name}): trades={result.trade_count} "
                  f"sharpe={result.sharpe:.2f} win_rate={result.win_rate:.1f}% "
                  f"fitness={row.fitness_score:.1f}", flush=True)
        except Exception as exc:
            errors += 1
            db.rollback()
            print(f"  ERROR {row.strategy_id}: {exc}", flush=True)

    return {"backtested": done, "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    db = get_session_factory()()

    print(f"=== Step 1: generate {args.n} index-futures candidates ===")
    gen = run_index_generation_cycle(db, n=args.n, generation=0)
    print(gen)

    print("\n=== Step 2: backtest unscored index-futures strategies ===")
    bt = backtest_unscored_index_strategies(db)
    print(bt)

    print("\n=== Step 3: lifecycle sweep (shared with stock pipeline) ===")
    sweep = run_lifecycle_sweep(db)
    print(sweep)

    n_total = db.query(StrategyV2).filter(StrategyV2.asset_class == "index_futures").count()
    n_scored = db.query(StrategyV2).filter(
        StrategyV2.asset_class == "index_futures", StrategyV2.fitness_score.isnot(None)
    ).count()
    print(f"\n=== Summary: {n_scored}/{n_total} index-futures strategies scored ===")

    db.close()


if __name__ == "__main__":
    main()

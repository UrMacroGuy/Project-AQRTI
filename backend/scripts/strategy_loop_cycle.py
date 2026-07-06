"""
Standalone strategy research cycle — runs ONE cycle of generate/backtest/
score/evolve, then exits. Meant to be launched as a separate OS process
(subprocess.Popen) by the scheduler every 5 minutes, NOT run in-thread inside
the API process.

Why this exists: the previous in-process version (aqrti/data/scheduler.py
_strategy_loop_job, run on a BackgroundScheduler thread) did CPU-heavy
synchronous work (backtesting ~100 strategies + scoring + evolution) that
starved the FastAPI event loop via GIL contention — even though it ran on a
"background" thread, Python's GIL means only one thread executes Python
bytecode at a time, so heavy CPU-bound work there still blocks the API from
handling HTTP requests. A separate process has its own GIL and can't do this.

Same logic as the old _strategy_loop_job, extracted verbatim:
  1. Count unscored candidates
  2. Generate 20 new candidates if backlog < 200
  3. Backtest up to 100 unscored (family-balanced)
  4. Score everything with trades but no score
  5. Evolve 10 offspring if backlog < 500

Usage:
    python scripts/strategy_loop_cycle.py
"""
import sys, os, time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)


def run_one_cycle() -> dict:
    from aqrti.database.session import get_db_session
    from aqrti.database.models import StrategyV2
    from strategies.strategy_generator import run_generation_cycle
    from strategies.fitness_engine import score_all_strategies
    from strategies.evolution_engine import evolve_population
    from strategies.strategy_research_loop import _backtest_unscored

    with get_db_session() as db:
        unscored = db.query(StrategyV2).filter(
            StrategyV2.fitness_score.is_(None),
            StrategyV2.status.in_(["candidate", "shadow"]),
            StrategyV2.dsl_json.isnot(None),
        ).count()

    new_count = 0
    if unscored < 200:
        with get_db_session() as db:
            gen = run_generation_cycle(db, n=20, generation=0)
        new_count = gen.get("persisted", 0)

    with get_db_session() as db:
        bt = _backtest_unscored(db, max_stocks=100)
    backtested = bt.get("backtested", 0)

    with get_db_session() as db:
        scored = score_all_strategies(db)

    evo_count = 0
    if unscored < 500:
        with get_db_session() as db:
            evo = evolve_population(db, n_offspring=10)
        evo_count = evo.get("created", 0)

    return {
        "unscored":   unscored,
        "generated":  new_count,
        "backtested": backtested,
        "scored":     scored.get("scored", 0),
        "evolved":    evo_count,
    }


if __name__ == "__main__":
    t0 = time.time()
    try:
        result = run_one_cycle()
        print(f"Strategy loop cycle done in {time.time()-t0:.1f}s: {result}", flush=True)
    except Exception as exc:
        print(f"Strategy loop cycle FAILED after {time.time()-t0:.1f}s: {exc}", flush=True)
        sys.exit(1)

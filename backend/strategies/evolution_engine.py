"""
Evolution Engine
Orchestrates the full evolutionary cycle:
  1. Select parents from the current population (tournament selection)
  2. Apply crossover + mutation to produce offspring
  3. Backtest offspring
  4. Score offspring
  5. Promote winners, retire losers
  6. Record evolution history

Does NOT deploy strategies automatically.
Human approval remains mandatory before 'active' status.
"""

from __future__ import annotations

import sys, os, json, random
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, MarketRegime
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL
from strategies.strategy_store import upsert_strategy, save_version, record_evolution_event
from strategies.mutation_engine import mutate
from strategies.crossover_engine import crossover
from strategies.strategy_backtester import backtest_and_update
from strategies.fitness_engine import score_strategy, compute_fitness
from strategies.strategy_lifecycle import run_lifecycle_sweep

log = get_logger("evolution_engine")

TOURNAMENT_SIZE    = 3      # tournament selection pool size
MUTATION_RATE      = 0.70   # 70% of offspring are mutations
CROSSOVER_RATE     = 0.30   # 30% are crossovers
MIN_PARENT_FITNESS = 40.0   # only evolve strategies above this threshold
BACKTEST_DAYS      = 365    # 1 year backtest window for offspring


def _tournament_select(
    population: list[StrategyV2],
    rng:        random.Random,
    k:          int = TOURNAMENT_SIZE,
) -> StrategyV2:
    """Pick k random candidates, return the one with highest fitness."""
    pool = rng.sample(population, min(k, len(population)))
    return max(pool, key=lambda s: s.fitness_score or 0.0)


def _current_regime(db: Session) -> str:
    row = (
        db.query(MarketRegime.regime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "BULL"


def _get_next_generation(db: Session) -> int:
    row = db.query(StrategyV2.generation).order_by(StrategyV2.generation.desc()).first()
    return (row[0] or 0) + 1 if row else 1


def evolve_population(
    db:            Session,
    n_offspring:   int = 20,
    seed:          Optional[int] = None,
    backtest_days: int = BACKTEST_DAYS,
) -> dict:
    """
    Run one evolution cycle: select → reproduce → evaluate → promote/retire.

    Args:
        db:            DB session
        n_offspring:   number of offspring to generate
        seed:          random seed
        backtest_days: how many days to backtest new offspring

    Returns:
        Summary dict of the evolution cycle.
    """
    rng       = random.Random(seed)
    regime    = _current_regime(db)
    next_gen  = _get_next_generation(db)

    # Select parent pool (strategies with backtest data and decent fitness)
    parents = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.trade_count    > 5,
            StrategyV2.fitness_score >= MIN_PARENT_FITNESS,
        )
        .order_by(StrategyV2.fitness_score.desc())
        .limit(50)
        .all()
    )

    if not parents:
        log.info("No eligible parents found for evolution")
        return {"status": "no_parents", "n_offspring": 0}

    created   = []
    skipped   = 0
    errors    = []

    end_date   = date.today()
    start_date = end_date - timedelta(days=backtest_days)

    for i in range(n_offspring):
        try:
            parent_a = _tournament_select(parents, rng)
            dsl_a    = StrategyDSL.from_json(parent_a.dsl_json)

            if rng.random() < MUTATION_RATE or len(parents) < 2:
                # Mutation
                child_dsl, op, desc = mutate(dsl_a, rng=rng)
                parent_ids          = [parent_a.strategy_id]
                operation           = f"mutation:{op}"
            else:
                # Crossover
                parent_b = _tournament_select(parents, rng)
                while parent_b.strategy_id == parent_a.strategy_id and len(parents) > 1:
                    parent_b = _tournament_select(parents, rng)
                dsl_b = StrategyDSL.from_json(parent_b.dsl_json)
                child_dsl, op, desc = crossover(
                    dsl_a, dsl_b,
                    fitness_a = parent_a.fitness_score or 0.0,
                    fitness_b = parent_b.fitness_score or 0.0,
                    rng=rng,
                )
                parent_ids = [parent_a.strategy_id, parent_b.strategy_id]
                operation  = f"crossover:{op}"

            child_id = child_dsl.strategy_id()

            # Skip if already exists
            existing = db.query(StrategyV2.id).filter(StrategyV2.strategy_id == child_id).first()
            if existing:
                skipped += 1
                continue

            # Persist child as candidate
            upsert_strategy(db, {
                "strategy_id":  child_id,
                "name":         child_dsl.name,
                "family":       child_dsl.family,
                "generation":   next_gen,
                "parent_ids":   json.dumps(parent_ids),
                "dsl_json":     child_dsl.to_json(),
                "allowed_regimes": json.dumps(child_dsl.allowed_regimes),
                "status":       "candidate",
            })
            save_version(db, child_id, child_dsl.to_json(), version=1,
                         change_type=operation, change_desc=desc)

            # Backtest
            bt_result = backtest_and_update(
                db, child_dsl, start_date=start_date, end_date=end_date
            )

            # Score
            child_row = db.query(StrategyV2).filter(StrategyV2.strategy_id == child_id).first()
            child_fitness = score_strategy(db, child_row) if child_row else 0.0

            # Record evolution event
            record_evolution_event(
                db,
                child_strategy_id   = child_id,
                operation           = operation,
                operation_detail    = {"desc": desc, "op": op},
                parent_strategy_ids = parent_ids,
                parent_fitness      = parent_a.fitness_score,
                child_fitness       = child_fitness,
                regime_at           = regime,
            )

            created.append({
                "strategy_id": child_id,
                "operation":   operation,
                "fitness":     child_fitness,
                "parent":      parent_ids[0],
            })

        except Exception as exc:
            log.error("Evolution error on offspring %d: %s", i, exc)
            errors.append(str(exc))

    db.commit()

    # Lifecycle sweep: promote winners, retire losers
    lifecycle = run_lifecycle_sweep(db)

    log.info(
        "Evolution cycle gen=%d: created=%d skipped=%d promoted=%d retired=%d errors=%d",
        next_gen, len(created), skipped,
        len(lifecycle.get("promoted", [])),
        len(lifecycle.get("retired", [])),
        len(errors),
    )

    return {
        "generation":  next_gen,
        "n_offspring": n_offspring,
        "created":     len(created),
        "skipped":     skipped,
        "errors":      len(errors),
        "promoted":    lifecycle.get("promoted", []),
        "retired":     lifecycle.get("retired", []),
        "regime_at":   regime,
        "offspring":   created,
    }

"""
Strategy Fitness Engine
Computes a 0-100 composite Fitness Score from 5 dimensions.

Fitness Dimensions (weighted):
  Profitability   (30%) — Sharpe, total return, profit factor
  Consistency     (25%) — win rate, expectancy stability
  Robustness      (20%) — works across multiple regimes, not overfit
  Regime Adaptability (15%) — performs specifically in current regime
  Longevity       (10%) — trade count (enough signals, not churning)

A score of 100 = ideal strategy. 55+ = promotable. <30 = retire.
"""

from __future__ import annotations

import sys, os
from datetime import date

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, MarketRegime
from aqrti.utils.logger import get_logger

log = get_logger("fitness_engine")

# ── Component weights ─────────────────────────────────────────
W_PROFITABILITY    = 0.30
W_CONSISTENCY      = 0.25
W_ROBUSTNESS       = 0.20
W_REGIME_ADAPT     = 0.15
W_LONGEVITY        = 0.10

# ── Normalization targets ─────────────────────────────────────
TARGET_SHARPE       = 2.0      # sharpe = 2.0 → 100% of profitability
TARGET_PROFIT_FACTOR = 2.5
TARGET_WIN_RATE     = 65.0
TARGET_TRADES       = 50       # 50+ trades = full longevity score
MIN_TRADES          = 5        # below this, longevity = 0


def profitability_score(sharpe: float, profit_factor: float, total_return: float) -> float:
    s1 = min(max(sharpe, 0.0) / TARGET_SHARPE, 1.0) * 50
    s2 = min(max(profit_factor - 1.0, 0.0) / (TARGET_PROFIT_FACTOR - 1.0), 1.0) * 30
    s3 = min(max(total_return, 0.0) / 50.0, 1.0) * 20    # 50% total return → full mark
    return round(s1 + s2 + s3, 2)


def consistency_score(win_rate: float, expectancy: float) -> float:
    s1 = min(max(win_rate, 0.0) / TARGET_WIN_RATE, 1.0) * 60
    s2 = min(max(expectancy, 0.0) / 3.0, 1.0) * 40       # 3% expectancy → full mark
    return round(s1 + s2, 2)


def robustness_score(
    sharpe: float,
    bull_sharpe: float,
    bear_sharpe: float,
    sideways_sharpe: float,
    volatile_sharpe: float,
    max_drawdown: float,
) -> float:
    # Regime breadth: how many regimes show positive sharpe
    regime_sharpes = [bull_sharpe, bear_sharpe, sideways_sharpe, volatile_sharpe]
    valid    = [s for s in regime_sharpes if s is not None and s != 0.0]
    positive = [s for s in valid if s > 0]
    breadth  = len(positive) / 4 * 40 if valid else 0.0

    # Drawdown penalty
    mdd_norm = min(abs(max_drawdown) / 30.0, 1.0)  # 30% drawdown → full penalty
    dd_score = (1.0 - mdd_norm) * 40

    # Sharpe consistency
    sc_score = min(max(sharpe, 0.0) / TARGET_SHARPE, 1.0) * 20

    return round(breadth + dd_score + sc_score, 2)


def regime_adaptability_score(
    current_regime: str,
    bull_sharpe: float,
    bear_sharpe: float,
    sideways_sharpe: float,
    volatile_sharpe: float,
) -> float:
    mapping = {
        "BULL":     bull_sharpe,
        "BEAR":     bear_sharpe,
        "SIDEWAYS": sideways_sharpe,
        "VOLATILE": volatile_sharpe,
    }
    regime_sharpe = mapping.get(current_regime, 0.0) or 0.0
    return round(min(max(regime_sharpe, 0.0) / TARGET_SHARPE, 1.0) * 100, 2)


def longevity_score(trade_count: int) -> float:
    if trade_count < MIN_TRADES:
        return 0.0
    return round(min(trade_count / TARGET_TRADES, 1.0) * 100, 2)


def compute_fitness(
    sharpe:          float,
    sortino:         float,
    win_rate:        float,
    profit_factor:   float,
    max_drawdown:    float,
    expectancy:      float,
    trade_count:     int,
    total_return:    float = 0.0,
    bull_sharpe:     float = 0.0,
    bear_sharpe:     float = 0.0,
    sideways_sharpe: float = 0.0,
    volatile_sharpe: float = 0.0,
    current_regime:  str   = "BULL",
) -> dict:
    """
    Compute full fitness breakdown and composite score.
    All input sharpe values may be None — treated as 0.
    """
    sharpe          = sharpe or 0.0
    sortino         = sortino or 0.0
    win_rate        = win_rate or 0.0
    profit_factor   = profit_factor or 1.0
    max_drawdown    = max_drawdown or 0.0
    expectancy      = expectancy or 0.0
    bull_sharpe     = bull_sharpe or 0.0
    bear_sharpe     = bear_sharpe or 0.0
    sideways_sharpe = sideways_sharpe or 0.0
    volatile_sharpe = volatile_sharpe or 0.0

    s_prof  = profitability_score(sharpe, profit_factor, total_return)
    s_cons  = consistency_score(win_rate, expectancy)
    s_rob   = robustness_score(sharpe, bull_sharpe, bear_sharpe, sideways_sharpe, volatile_sharpe, max_drawdown)
    s_regime = regime_adaptability_score(current_regime, bull_sharpe, bear_sharpe, sideways_sharpe, volatile_sharpe)
    s_long  = longevity_score(trade_count)

    composite = (
        s_prof   * W_PROFITABILITY +
        s_cons   * W_CONSISTENCY +
        s_rob    * W_ROBUSTNESS +
        s_regime * W_REGIME_ADAPT +
        s_long   * W_LONGEVITY
    )
    composite = round(min(100.0, max(0.0, composite)), 2)

    return {
        "fitness_score":       composite,
        "profitability":       s_prof,
        "consistency":         s_cons,
        "robustness":          s_rob,
        "regime_adaptability": s_regime,
        "longevity":           s_long,
        "current_regime":      current_regime,
    }


def score_strategy(db: Session, strategy: StrategyV2) -> float:
    """
    Compute fitness score for an existing StrategyV2 row.
    Updates fitness_score in DB. Returns the score.
    """
    # Determine current regime
    regime_row = (
        db.query(MarketRegime.regime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    current_regime = regime_row[0] if regime_row else "BULL"

    result = compute_fitness(
        sharpe          = strategy.sharpe or 0.0,
        sortino         = strategy.sortino or 0.0,
        win_rate        = strategy.win_rate or 0.0,
        profit_factor   = strategy.profit_factor or 1.0,
        max_drawdown    = strategy.max_drawdown or 0.0,
        expectancy      = strategy.expectancy or 0.0,
        trade_count     = strategy.trade_count or 0,
        bull_sharpe     = strategy.bull_sharpe or 0.0,
        bear_sharpe     = strategy.bear_sharpe or 0.0,
        sideways_sharpe = strategy.sideways_sharpe or 0.0,
        volatile_sharpe = strategy.volatile_sharpe or 0.0,
        current_regime  = current_regime,
    )
    strategy.fitness_score = result["fitness_score"]
    log.debug("Fitness %s -> %.1f", strategy.strategy_id, result["fitness_score"])
    return result["fitness_score"]


def score_all_strategies(db: Session) -> dict:
    """Score every unscored or backtested strategy. Commits to DB."""
    rows = (
        db.query(StrategyV2)
        .filter(StrategyV2.trade_count > 0)
        .all()
    )
    scored = 0
    for r in rows:
        score_strategy(db, r)
        scored += 1
    db.commit()
    log.info("Scored %d strategies", scored)
    return {"scored": scored}

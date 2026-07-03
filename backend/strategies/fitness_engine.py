"""
Strategy Fitness Engine v2
Computes a 0-100 composite Fitness Score from 6 dimensions.

Fitness Dimensions (weighted):
  Profitability      (28%) — Sharpe, total return, profit factor
  Consistency        (22%) — win rate, expectancy stability
  Robustness         (18%) — works across multiple regimes, not overfit
  Cost Efficiency    (15%) — net-of-cost performance (filters strategies that
                              look good gross but die on transaction friction)
  Regime Adaptability(12%) — performs specifically in current regime
  Longevity          ( 5%) — trade count (enough signals)

Key changes from v1:
  - Cost Efficiency dimension: penalises strategies where avg trade P&L is
    close to round-trip cost (~0.28%). A strategy averaging 0.3%/trade is
    barely covering costs and will likely lose money live.
  - Walk-forward penalty: if avg_holding_days < 3, score is halved
    (ultra-short holding periods amplify cost drag dramatically).
  - Minimum quality gates applied before scoring (hard zeros):
    trade_count < MIN_TRADES → longevity = 0
    net_expectancy (after costs) < 0 → cost_efficiency = 0
  - Profit factor target raised to 2.0 (was 1.8) — must beat cost friction.
  - Sharpe target raised to 1.2 (was 1.0) — Indian equity benchmark is ~0.8.
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
W_PROFITABILITY    = 0.28
W_CONSISTENCY      = 0.22
W_ROBUSTNESS       = 0.18
W_COST_EFFICIENCY  = 0.15
W_REGIME_ADAPT     = 0.12
W_LONGEVITY        = 0.05

# ── Normalization targets ─────────────────────────────────────
TARGET_SHARPE        = 1.2     # raised — Nifty50 long-only ≈ 0.8; must beat it
TARGET_PROFIT_FACTOR = 2.0     # raised — must clear cost friction
TARGET_WIN_RATE      = 52.0    # 52% realistic for systematic strategies on Indian equities
TARGET_TRADES        = 100     # 100+ trades = statistically meaningful over 3yr NSE window
MIN_TRADES           = 10      # hard floor — backtester needs ≥10 trades to avoid noise scores

# ── Cost model constants (match backtester) ───────────────────
ROUND_TRIP_COST_PCT  = 0.28    # % — realistic NSE delivery round-trip
MIN_EXPECTANCY_NET   = 0.10    # % per trade — must net > 0.10% after costs


def profitability_score(sharpe: float, profit_factor: float, total_return: float) -> float:
    # Sharpe: 0 at 0, full at TARGET_SHARPE (with soft penalty for negative)
    sharpe_norm = max(sharpe + 0.3, 0.0) / (TARGET_SHARPE + 0.3)
    s1 = min(sharpe_norm, 1.0) * 45
    s2 = min(max(profit_factor - 1.0, 0.0) / (TARGET_PROFIT_FACTOR - 1.0), 1.0) * 35
    s3 = min(max(total_return, 0.0) / 25.0, 1.0) * 20   # 25% total return → full mark
    return round(s1 + s2 + s3, 2)


def consistency_score(win_rate: float, expectancy: float) -> float:
    s1 = min(max(win_rate, 0.0) / TARGET_WIN_RATE, 1.0) * 60
    s2 = min(max(expectancy, 0.0) / 2.0, 1.0) * 40    # 2.0% expectancy → full mark
    return round(s1 + s2, 2)


def robustness_score(
    sharpe: float,
    bull_sharpe: float,
    bear_sharpe: float,
    sideways_sharpe: float,
    volatile_sharpe: float,
    max_drawdown: float,
    avg_holding_days: float = 0.0,
) -> float:
    regime_sharpes = [bull_sharpe, bear_sharpe, sideways_sharpe, volatile_sharpe]
    valid    = [s for s in regime_sharpes if s is not None and s != 0.0]
    positive = [s for s in valid if s > 0]
    breadth  = len(positive) / 4 * 40 if valid else 0.0

    # Drawdown penalty — tighter (20% = full penalty, was 30%)
    mdd_norm = min(abs(max_drawdown) / 20.0, 1.0)
    dd_score = (1.0 - mdd_norm) * 40

    sc_score = min(max(sharpe, 0.0) / TARGET_SHARPE, 1.0) * 20

    score = breadth + dd_score + sc_score

    # Walk-forward penalty: very short holding → cost drag explodes live
    if avg_holding_days > 0 and avg_holding_days < 3:
        score *= 0.5   # halve for strategies that flip positions < 3 days

    return round(score, 2)


def cost_efficiency_score(
    expectancy: float,        # avg trade return %
    avg_holding_days: float,  # avg days held
    trade_count: int,
) -> float:
    """
    Measures how much of the gross return survives transaction costs.

    A strategy with 0.30% avg trade and 0.28% round-trip cost has
    essentially zero net edge. We require at least MIN_EXPECTANCY_NET
    net expectancy before giving any credit.

    Also penalises very-high-frequency strategies (< 5 days avg hold)
    because live cost drag vs. backtest cost model is higher.
    """
    if trade_count < MIN_TRADES:
        return 0.0

    # Expectancy from backtester is already net-of-cost (cost deducted per trade).
    # Additional buffer: live execution vs backtest model variance.
    LIVE_BUFFER_PCT = 0.05   # reduced 0.10→0.05 — backtester already models NSE costs accurately
    net_expectancy = expectancy - LIVE_BUFFER_PCT
    if net_expectancy < 0:
        return 0.0

    # Base score: how much does net expectancy exceed the cost floor
    base = min(net_expectancy / 2.0, 1.0) * 70   # 2% net expectancy → 70 pts

    # Frequency bonus: longer holds = less cost drag per day
    if avg_holding_days >= 10:
        freq_score = 30.0
    elif avg_holding_days >= 5:
        freq_score = 20.0
    elif avg_holding_days >= 3:
        freq_score = 10.0
    else:
        freq_score = 0.0   # < 3 days: costs eat all edge

    return round(base + freq_score, 2)


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
    # Graded: 0 at 10, 50 at 50 trades, full (100) at 100+ trades
    return round(min(trade_count / TARGET_TRADES, 1.0) * 100, 2)


def compute_fitness(
    sharpe:           float,
    sortino:          float,
    win_rate:         float,
    profit_factor:    float,
    max_drawdown:     float,
    expectancy:       float,
    trade_count:      int,
    total_return:     float = 0.0,
    bull_sharpe:      float = 0.0,
    bear_sharpe:      float = 0.0,
    sideways_sharpe:  float = 0.0,
    volatile_sharpe:  float = 0.0,
    current_regime:   str   = "BULL",
    avg_holding_days: float = 0.0,
) -> dict:
    """
    Compute full fitness breakdown and composite score.
    All input sharpe values may be None — treated as 0.
    Sharpes capped at 3.0, profit_factor capped at 5.0.
    """
    SHARPE_CAP = 3.0
    sharpe          = min(sharpe or 0.0, SHARPE_CAP)
    sortino         = min(sortino or 0.0, 6.0)
    win_rate        = win_rate or 0.0
    profit_factor   = min(profit_factor or 1.0, 5.0)
    max_drawdown    = max_drawdown or 0.0
    expectancy      = min(expectancy or 0.0, 10.0)
    bull_sharpe     = min(bull_sharpe or 0.0, SHARPE_CAP)
    bear_sharpe     = min(bear_sharpe or 0.0, SHARPE_CAP)
    sideways_sharpe = min(sideways_sharpe or 0.0, SHARPE_CAP)
    volatile_sharpe = min(volatile_sharpe or 0.0, SHARPE_CAP)
    avg_holding_days = avg_holding_days or 0.0

    s_prof   = profitability_score(sharpe, profit_factor, total_return)
    s_cons   = consistency_score(win_rate, expectancy)
    s_rob    = robustness_score(sharpe, bull_sharpe, bear_sharpe, sideways_sharpe,
                                volatile_sharpe, max_drawdown, avg_holding_days)
    s_cost   = cost_efficiency_score(expectancy, avg_holding_days, trade_count)
    s_regime = regime_adaptability_score(current_regime, bull_sharpe, bear_sharpe,
                                         sideways_sharpe, volatile_sharpe)
    s_long   = longevity_score(trade_count)

    composite = (
        s_prof   * W_PROFITABILITY   +
        s_cons   * W_CONSISTENCY     +
        s_rob    * W_ROBUSTNESS      +
        s_cost   * W_COST_EFFICIENCY +
        s_regime * W_REGIME_ADAPT    +
        s_long   * W_LONGEVITY
    )
    composite = round(min(100.0, max(0.0, composite)), 2)

    return {
        "fitness_score":       composite,
        "profitability":       s_prof,
        "consistency":         s_cons,
        "robustness":          s_rob,
        "cost_efficiency":     s_cost,
        "regime_adaptability": s_regime,
        "longevity":           s_long,
        "current_regime":      current_regime,
        "net_expectancy":      round(expectancy - 0.10, 4),   # live-buffer adjusted
    }


def score_strategy(db: Session, strategy: StrategyV2) -> float:
    """
    Compute fitness score for an existing StrategyV2 row.
    Updates fitness_score in DB. Returns the score.
    """
    regime_row = (
        db.query(MarketRegime.regime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    current_regime = regime_row[0] if regime_row else "BULL"

    result = compute_fitness(
        sharpe           = strategy.sharpe or 0.0,
        sortino          = strategy.sortino or 0.0,
        win_rate         = strategy.win_rate or 0.0,
        profit_factor    = strategy.profit_factor or 1.0,
        max_drawdown     = strategy.max_drawdown or 0.0,
        expectancy       = strategy.expectancy or 0.0,
        trade_count      = strategy.trade_count or 0,
        total_return     = 0.0,
        bull_sharpe      = strategy.bull_sharpe or 0.0,
        bear_sharpe      = strategy.bear_sharpe or 0.0,
        sideways_sharpe  = strategy.sideways_sharpe or 0.0,
        volatile_sharpe  = strategy.volatile_sharpe or 0.0,
        current_regime   = current_regime,
        avg_holding_days = strategy.avg_holding_days or 0.0,
    )
    strategy.fitness_score = result["fitness_score"]
    log.debug("Fitness %s -> %.1f", strategy.strategy_id, result["fitness_score"])
    return result["fitness_score"]


def score_all_strategies(db: Session) -> dict:
    """Score every strategy that has backtest results. Commits to DB."""
    rows = db.query(StrategyV2).filter(StrategyV2.trade_count > 0).all()
    scored = 0
    for r in rows:
        score_strategy(db, r)
        scored += 1
    db.commit()
    log.info("Scored %d strategies", scored)
    return {"scored": scored}


def rescore_all(db: Session) -> dict:
    """Force-rescore ALL strategies that have trade data."""
    rows = db.query(StrategyV2).filter(StrategyV2.trade_count > 0).all()
    updated = 0
    for r in rows:
        old = r.fitness_score
        score_strategy(db, r)
        if r.fitness_score != old:
            updated += 1
    db.commit()
    log.info("Rescored %d strategies (%d changed)", len(rows), updated)
    return {"total": len(rows), "updated": updated}

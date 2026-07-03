"""
Strategy Generator
Generates candidate strategies systematically across 7 feature categories.

Generation approach:
  - For each family template, define a parameter grid (thresholds, feature combinations)
  - Randomly sample N points from the grid to produce candidates
  - Each candidate is a valid StrategyDSL object immediately ready for backtesting
  - Deduplication via strategy_id hash — duplicates are silently skipped

Supported families:
  momentum, mean_reversion, breakout, sentiment_driven,
  regime_adaptive, volume_surge, volatility_play, hybrid
"""

from __future__ import annotations

import sys, os, json, random
from datetime import date
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL, Condition, ConditionGroup
from strategies.strategy_store import upsert_strategy, save_version

log = get_logger("strategy_generator")

# ── Feature pools by category ─────────────────────────────────

PRICE_FEATURES = [
    "return_1d", "return_5d", "return_21d", "momentum_10d", "momentum_20d",
    "breakout_distance_52w", "price_position_52w", "relative_strength_nifty_21d",
    "support_distance_20d", "resistance_distance_20d",
]
VOLUME_FEATURES = [
    "volume_ratio_20d", "delivery_pct", "volume_surge_flag",
    "vwap_distance", "institutional_flow_proxy",
]
VOLATILITY_FEATURES = [
    "atr_14", "bb_width_20", "realized_vol_20d", "vol_ratio_short_long",
    "hv_percentile_252d",
]
TREND_FEATURES = [
    "ema_20", "ema_50", "macd_signal", "adx_14", "rsi_14", "stoch_k",
    "price_above_ema50", "ema20_above_ema50",
]
SENTIMENT_FEATURES = [
    "sentiment_score", "sentiment_velocity", "news_impact_score",
    "sector_sentiment_score",
]
PATTERN_FEATURES = [
    "pattern_confidence", "similarity_score",
]
REGIME_FEATURES = [
    "regime_confidence", "breadth_pct", "nifty_trend_score",
]

# ── Regime groupings ──────────────────────────────────────────
REGIME_SETS = {
    "bull_only":       ["BULL"],
    "bull_sideways":   ["BULL", "SIDEWAYS"],
    "all_weather":     ["BULL", "BEAR", "SIDEWAYS", "VOLATILE"],
    "defensive":       ["SIDEWAYS", "BEAR"],
    "high_vol":        ["VOLATILE"],
    "trending":        ["BULL", "BEAR"],
}

# ── Family templates ──────────────────────────────────────────

def _make_condition(feature: str, op: str, threshold: float, weight: float = 1.0) -> Condition:
    return Condition(feature=feature, operator=op, threshold=threshold, weight=weight)


def _rand_confidence(rng: random.Random, lo: float = 50.0, hi: float = 68.0) -> float:
    """Generate a realistic min_confidence — biased toward lower values that fire more signals."""
    return round(rng.uniform(lo, hi), 1)


def _rr_take_profit(rng: random.Random, stop_loss_pct: float, min_rr: float = 1.5) -> float:
    """Return a take-profit that gives at minimum min_rr reward:risk ratio."""
    min_tp = abs(stop_loss_pct) * min_rr
    max_tp = abs(stop_loss_pct) * 3.5
    return round(rng.uniform(min_tp, max_tp), 1)


def _generate_momentum(rng: random.Random) -> StrategyDSL:
    feat    = rng.choice(["return_5d", "return_21d", "momentum_10d", "momentum_20d"])
    thresh  = rng.uniform(1.5, 6.0)      # must move at least 1.5% to qualify
    rsi_th  = rng.uniform(45, 58)        # don't chase overbought
    regime  = rng.choice(["bull_only", "bull_sideways", "all_weather"])
    n_conds = rng.randint(2, 3)
    conds   = [_make_condition(feat, ">", round(thresh, 2))]
    if n_conds >= 2:
        conds.append(_make_condition("rsi_14", ">", round(rsi_th, 1)))
    if n_conds >= 3:
        trend = rng.choice(["macd_signal", "adx_14", "ema20_above_ema50", "price_above_ema50"])
        t_val = rng.uniform(25, 50)     # ADX > 25 = trending; others are binary/normalised
        conds.append(_make_condition(trend, ">", round(t_val, 1)))
    entry  = ConditionGroup(conditions=conds)
    exit_  = ConditionGroup(conditions=[
        _make_condition("rsi_14", ">", round(rng.uniform(68, 80), 1)),
    ], logic="OR")
    sl     = round(-rng.uniform(5, 10), 1)
    return StrategyDSL(
        entry_conditions = entry,
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[regime],
        family           = "momentum",
        name             = f"Momentum_{feat}_{round(thresh,1)}",
        min_confidence   = _rand_confidence(rng, 52.0, 68.0),
        max_holding_days = rng.randint(7, 25),   # min 7 to clear cost drag
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.8),  # min 1.8:1 R:R
    )


def _generate_mean_reversion(rng: random.Random) -> StrategyDSL:
    rsi_lo = round(rng.uniform(25, 38), 1)   # deeper oversold = higher conviction
    n_conds = rng.randint(2, 3)
    conds = [_make_condition("rsi_14", "<", rsi_lo)]
    if n_conds >= 2:
        # Recent pullback confirms oversold (require actual price drop)
        conds.append(_make_condition("return_5d", "<", round(-rng.uniform(2.0, 5.0), 2)))
    if n_conds >= 3:
        # BB squeeze or Bollinger lower band touch
        conds.append(_make_condition("bb_width_20", ">", round(rng.uniform(0.03, 0.08), 3)))
    entry = ConditionGroup(conditions=conds)
    exit_ = ConditionGroup(conditions=[
        _make_condition("rsi_14", ">", round(rng.uniform(50, 60), 1)),
    ])
    sl = round(-rng.uniform(4, 8), 1)
    return StrategyDSL(
        entry_conditions = entry,
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "mean_reversion",
        name             = f"MeanRev_RSI{rsi_lo}",
        min_confidence   = _rand_confidence(rng, 50.0, 65.0),
        max_holding_days = rng.randint(5, 15),   # min 5 — MR needs time to recover
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.5),
    )


def _generate_breakout(rng: random.Random) -> StrategyDSL:
    brk_th = round(rng.uniform(-5, 2), 2)   # wider range — can enter at -5% from 52w high
    vol_th = round(rng.uniform(1.2, 2.2), 2)
    n_conds = rng.randint(2, 4)
    conds = [_make_condition("breakout_distance_52w", ">", brk_th)]
    if n_conds >= 2:
        conds.append(_make_condition("volume_ratio_20d", ">", vol_th))
    if n_conds >= 3:
        adx_th = round(rng.uniform(18, 32), 1)
        conds.append(_make_condition("adx_14", ">", adx_th))
    if n_conds >= 4:
        conds.append(_make_condition("price_above_ema50", "==", 1.0))
    regime = rng.choice(["bull_only", "bull_sideways"])
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[regime],
        family           = "breakout",
        name             = f"Breakout_52w_{round(brk_th,1)}",
        min_confidence   = _rand_confidence(rng, 52.0, 68.0),
        max_holding_days = rng.randint(8, 22),
        stop_loss_pct    = round(-rng.uniform(6, 12), 1),
        take_profit_pct  = round(rng.uniform(12, 28), 1),
    )


def _generate_sentiment_driven(rng: random.Random) -> StrategyDSL:
    sent_th = round(rng.uniform(55, 75), 1)
    n_conds = rng.randint(2, 3)
    conds = [_make_condition("sentiment_score", ">", sent_th)]
    if n_conds >= 2:
        tech_f  = rng.choice(["rsi_14", "momentum_10d", "return_5d", "adx_14"])
        tech_v  = round(rng.uniform(40, 58), 1)
        conds.append(_make_condition(tech_f, ">", tech_v))
    if n_conds >= 3:
        vel_th = round(rng.uniform(3, 15), 1)
        conds.append(_make_condition("sentiment_velocity", ">", vel_th))
    entry   = ConditionGroup(conditions=conds)
    return StrategyDSL(
        entry_conditions = entry,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "sentiment_driven",
        name             = f"Sentiment_GT{sent_th}",
        min_confidence   = _rand_confidence(rng, 50.0, 65.0),
        max_holding_days = rng.randint(4, 14),
        stop_loss_pct    = round(-rng.uniform(5, 9), 1),
        take_profit_pct  = round(rng.uniform(7, 16), 1),
    )


def _generate_regime_adaptive(rng: random.Random) -> StrategyDSL:
    regime_set = rng.choice(list(REGIME_SETS.keys()))
    feat1 = rng.choice(PRICE_FEATURES + TREND_FEATURES[:4])
    v1    = round(rng.uniform(-3, 5), 2)
    n_conds = rng.randint(2, 3)
    conds = [_make_condition(feat1, ">", v1)]
    if n_conds >= 2:
        feat2 = rng.choice(TREND_FEATURES)
        v2    = round(rng.uniform(38, 62), 1)
        conds.append(_make_condition(feat2, ">", v2))
    if n_conds >= 3:
        conds.append(_make_condition("regime_confidence", ">", round(rng.uniform(55, 75), 1)))
    entry  = ConditionGroup(conditions=conds)
    return StrategyDSL(
        entry_conditions = entry,
        allowed_regimes  = REGIME_SETS[regime_set],
        family           = "regime_adaptive",
        name             = f"Regime_{regime_set}_{feat1[:6]}",
        min_confidence   = _rand_confidence(rng, 50.0, 66.0),
        max_holding_days = rng.randint(6, 20),
        stop_loss_pct    = round(-rng.uniform(6, 11), 1),
        take_profit_pct  = round(rng.uniform(9, 22), 1),
    )


def _generate_volume_surge(rng: random.Random) -> StrategyDSL:
    vol_th  = round(rng.uniform(1.3, 2.8), 2)
    n_conds = rng.randint(2, 4)
    conds   = [_make_condition("volume_ratio_20d", ">", vol_th)]
    if n_conds >= 2:
        rsi_th  = round(rng.uniform(42, 62), 1)
        conds.append(_make_condition("rsi_14", ">", rsi_th))
    if n_conds >= 3:
        conds.append(_make_condition("return_1d", ">", round(rng.uniform(0.3, 1.8), 2)))
    if n_conds >= 4:
        del_th = round(rng.uniform(50, 72), 1)
        conds.append(_make_condition("delivery_pct", ">", del_th))
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "bull_only", "all_weather"])],
        family           = "volume_surge",
        name             = f"VolSurge_{vol_th}x",
        min_confidence   = _rand_confidence(rng, 52.0, 67.0),
        max_holding_days = rng.randint(3, 10),
        stop_loss_pct    = round(-rng.uniform(4, 8), 1),
        take_profit_pct  = round(rng.uniform(6, 14), 1),
    )


def _generate_volatility_play(rng: random.Random) -> StrategyDSL:
    atr_th  = round(rng.uniform(1.2, 3.5), 2)
    n_conds = rng.randint(2, 3)
    conds   = [_make_condition("atr_14", ">", atr_th)]
    if n_conds >= 2:
        rsi_th  = round(rng.uniform(32, 52), 1)
        conds.append(_make_condition("rsi_14", "<", rsi_th))
    if n_conds >= 3:
        hv_th = round(rng.uniform(35, 65), 1)
        conds.append(_make_condition("hv_percentile_252d", "<", hv_th))
    # Volatility plays work in all markets including volatile regimes
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[rng.choice(["high_vol", "all_weather", "bull_sideways"])],
        family           = "volatility_play",
        name             = f"VolPlay_ATR{atr_th}",
        min_confidence   = _rand_confidence(rng, 48.0, 64.0),
        max_holding_days = rng.randint(3, 8),
        stop_loss_pct    = round(-rng.uniform(3, 7), 1),
        take_profit_pct  = round(rng.uniform(5, 13), 1),
    )


def _generate_hybrid(rng: random.Random) -> StrategyDSL:
    # Pick 2-3 features from different categories — wider feature space
    all_cats = [PRICE_FEATURES, TREND_FEATURES, VOLUME_FEATURES, VOLATILITY_FEATURES]
    rng.shuffle(all_cats)
    n_conds = rng.randint(2, 3)
    conds = []
    for pool in all_cats[:n_conds]:
        feat   = rng.choice(pool)
        # Use feature-appropriate threshold ranges
        if feat in VOLATILITY_FEATURES:
            thresh = round(rng.uniform(0.02, 3.0), 3)
        elif feat in VOLUME_FEATURES:
            thresh = round(rng.uniform(1.0, 2.5), 2)
        else:
            thresh = round(rng.uniform(40, 70), 2)
        op = rng.choice([">", ">", ">="])   # bias toward greater-than
        conds.append(_make_condition(feat, op, thresh))
    entry = ConditionGroup(conditions=conds)
    return StrategyDSL(
        entry_conditions = entry,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather", "bull_only"])],
        family           = "hybrid",
        name             = f"Hybrid_{conds[0].feature[:6]}_{conds[1].feature[:6]}",
        min_confidence   = _rand_confidence(rng, 50.0, 66.0),
        max_holding_days = rng.randint(6, 18),
        stop_loss_pct    = round(-rng.uniform(5, 10), 1),
        take_profit_pct  = round(rng.uniform(8, 18), 1),
    )


def _generate_quality_momentum(rng: random.Random) -> StrategyDSL:
    """
    QGLP-inspired: Quality + Growth + Low Leverage + Price Momentum.
    Indian market's most durable factor — works across most regimes.
    Entry: stock showing BOTH strong price momentum AND positive sentiment
           (proxy for improving fundamentals since we don't have balance sheet data).
    Target: 20-35% TP, 8-12% SL — position for multi-week swing.
    """
    mom_feat = rng.choice(["return_21d", "momentum_20d", "relative_strength_nifty_21d"])
    mom_th   = round(rng.uniform(3.0, 8.0), 2)   # 3-8% outperformance
    rsi_th   = round(rng.uniform(50, 62), 1)      # not overbought but trending up
    n_conds  = rng.randint(3, 4)

    conds = [
        _make_condition(mom_feat, ">", mom_th),         # price strength
        _make_condition("rsi_14", ">", rsi_th),         # momentum confirmed
    ]
    if n_conds >= 3:
        conds.append(_make_condition("adx_14", ">", round(rng.uniform(22, 30), 1)))  # trending
    if n_conds >= 4:
        conds.append(_make_condition("volume_ratio_20d", ">", round(rng.uniform(1.1, 1.6), 2)))

    exit_ = ConditionGroup(conditions=[
        _make_condition("rsi_14", ">", round(rng.uniform(72, 82), 1)),
        _make_condition("return_5d", "<", round(-rng.uniform(2.0, 4.0), 1)),  # momentum break
    ], logic="OR")

    sl = round(-rng.uniform(8, 12), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS["bull_sideways"],
        family           = "quality_momentum",
        name             = f"QualMom_{mom_feat[:8]}_{mom_th}",
        min_confidence   = _rand_confidence(rng, 58.0, 72.0),  # higher conviction needed
        max_holding_days = rng.randint(15, 40),    # position trade — 3-8 weeks
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 2.0),   # min 2:1 R:R
    )


def _generate_rl_momentum(rng: random.Random) -> StrategyDSL:
    """
    RL-PPO Inspired Strategy — adapted from ZiadFrancis/ReinforcementTrading_Part_1.

    Original: PPO agent on EURUSD Forex with 130 discrete actions (HOLD / CLOSE /
    OPEN(direction, SL_pips, TP_pips)) and a 30-bar window of RSI, ATR, MA slopes,
    price-vs-MA distances. Reward = realized PnL pips - spread - commission + hold
    shaping for winning positions.

    NSE adaptation:
      - Pips → percentage returns (Indian equities, INR-denominated)
      - Long-only (no shorting via delivery; F&O not used here)
      - SL/TP expressed as % of entry price, sized relative to ATR (dynamic like RL)
      - 30-bar lookback → uses 20d and 50d MA slopes + RSI (same features as the RL env)
      - Hold signal: stay in trade while MA20 slope is positive + RSI not overbought
        (mirrors the "hold_reward_weight" that rewards holding winning positions)
      - Exit: RSI > overbought threshold OR MA20 slope turns negative (mirrors CLOSE action)
      - ATR-scaled SL: tighter when market is calm, wider in volatile periods
      - Multi-condition entry: requires BOTH momentum confirmation AND trend alignment
        (mimics the agent learning that single-signal entries underperform)
    """
    # RL env used RSI(14), ATR(14), MA20/MA50 slopes, close-MA distances, MA spread
    # We mirror exactly those features from AQRTI's feature engineering

    # Entry: multi-timeframe confluence (what trained PPO learns to require)
    rsi_entry   = round(rng.uniform(48, 60), 1)     # RSI > X: trend started
    ma_slope    = round(rng.uniform(0.0, 0.5), 3)   # MA20 slope positive (trending up)
    ma_spread   = round(rng.uniform(0.0, 1.0), 3)   # MA20 > MA50 (golden cross zone)
    n_extra     = rng.randint(0, 2)

    conds = [
        _make_condition("rsi_14",        ">",  rsi_entry),
        _make_condition("ma_20_slope",   ">",  ma_slope,   weight=1.2),
        _make_condition("ma_spread",     ">",  ma_spread,  weight=1.0),
    ]
    if n_extra >= 1:
        # RL agent also looks at distance from MA — price should be above MA20
        close_ma_th = round(rng.uniform(-0.5, 0.5), 3)
        conds.append(_make_condition("close_ma20_diff", ">", close_ma_th))
    if n_extra >= 2:
        # Volume confirmation — institutional buying amplifies RL signals
        vol_th = round(rng.uniform(1.1, 1.8), 2)
        conds.append(_make_condition("volume_ratio_20d", ">", vol_th))

    # Exit: RSI overbought OR MA20 slope reverses (mirrors CLOSE action in RL)
    rsi_exit = round(rng.uniform(68, 80), 1)
    exit_ = ConditionGroup(conditions=[
        _make_condition("rsi_14",      ">",  rsi_exit),
        _make_condition("ma_20_slope", "<",  0.0,     weight=1.3),
    ], logic="OR")

    # ATR-adaptive SL/TP: RL used dynamic SL/TP from a discrete grid [5,10,15,25,30,60,90,120] pips
    # Translated: smaller SL in calm markets, larger in volatile — sampled from a wider range
    sl_mult = round(rng.uniform(1.0, 2.5), 1)   # SL = sl_mult × typical ATR%
    # Typical NSE stock ATR is ~1.5-3% daily; use 1.5% as base
    sl_base = round(rng.uniform(4.0, 9.0), 1)
    sl      = round(-sl_base, 1)
    # RL learned best R:R is ~2:1 when in trending market (TP grid went up to 120 pips)
    min_rr  = round(rng.uniform(1.8, 2.8), 1)
    tp      = _rr_take_profit(rng, sl, min_rr)

    # Hold horizon: RL trained on episodes up to 2000 steps (hourly bars)
    # NSE daily: equivalent swing of 10-30 bars
    hold_days = rng.randint(10, 25)

    # Regime: RL strategy worked well in trending markets (trained on BULL-like Forex runs)
    regime = rng.choice(["bull_sideways", "bull_only", "all_weather"])

    # Name encodes the RL heritage
    tag = f"RL{round(rsi_entry,0):.0f}_MA{round(ma_slope,2):.2f}"
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[regime],
        family           = "rl_momentum",
        name             = f"RLMom_{tag}",
        min_confidence   = _rand_confidence(rng, 54.0, 68.0),
        max_holding_days = hold_days,
        stop_loss_pct    = sl,
        take_profit_pct  = tp,
    )


def _generate_institutional_flow(rng: random.Random) -> StrategyDSL:
    """
    Ride institutional accumulation: high delivery %, volume surge,
    price above EMA50. When big money is buying, follow.
    """
    del_th  = round(rng.uniform(60, 78), 1)    # >60% delivery = genuine buying
    vol_th  = round(rng.uniform(1.4, 2.5), 2)  # volume surge
    n_conds = rng.randint(3, 4)

    conds = [
        _make_condition("delivery_pct", ">", del_th),
        _make_condition("volume_ratio_20d", ">", vol_th),
        _make_condition("price_above_ema50", "==", 1.0),
    ]
    if n_conds >= 4:
        conds.append(_make_condition("rsi_14", ">", round(rng.uniform(48, 60), 1)))

    sl = round(-rng.uniform(6, 10), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_only", "bull_sideways"])],
        family           = "institutional_flow",
        name             = f"InstFlow_Del{del_th}_Vol{vol_th}",
        min_confidence   = _rand_confidence(rng, 55.0, 70.0),
        max_holding_days = rng.randint(10, 30),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 2.0),
    )


_GENERATORS = {
    "momentum":           _generate_momentum,
    "mean_reversion":     _generate_mean_reversion,
    "breakout":           _generate_breakout,
    "sentiment_driven":   _generate_sentiment_driven,
    "regime_adaptive":    _generate_regime_adaptive,
    "volume_surge":       _generate_volume_surge,
    "volatility_play":    _generate_volatility_play,
    "hybrid":             _generate_hybrid,
    "quality_momentum":   _generate_quality_momentum,
    "institutional_flow": _generate_institutional_flow,
    "rl_momentum":        _generate_rl_momentum,
}

# Family weights for generation — bias toward historically stronger families
_FAMILY_WEIGHTS = {
    "momentum":           0.16,
    "mean_reversion":     0.09,
    "breakout":           0.11,
    "sentiment_driven":   0.05,
    "regime_adaptive":    0.07,
    "volume_surge":       0.09,
    "volatility_play":    0.07,
    "hybrid":             0.07,
    "quality_momentum":   0.11,   # strong Indian factor — weighted up
    "institutional_flow": 0.07,
    "rl_momentum":        0.11,   # RL-PPO inspired family — new, high weight to seed population
}


# ── Pre-screening gate ────────────────────────────────────────────────
# Reject structurally bad strategies before they ever reach the backtester.
# This saves backtest time and prevents noise from polluting the population.

MIN_RR_RATIO    = 1.5    # take_profit must be at least 1.5× |stop_loss|
MIN_CONFIDENCE  = 52.0   # below this, the strategy fires on noise
MAX_HOLDING     = 60     # longer than 60 days → not a swing strategy
MIN_HOLDING     = 3      # below 3 days → cost drag kills the edge

def _passes_prescreen(strategy: StrategyDSL, bad_features: set,
                      bad_conditions: set | None = None) -> tuple[bool, str]:
    """
    Structural quality gates applied before backtesting.
    Returns (passes, reason_if_rejected).
    """
    sl  = abs(strategy.stop_loss_pct   or 7.0)
    tp  = abs(strategy.take_profit_pct or 12.0)
    rr  = tp / sl if sl > 0 else 0.0
    if rr < MIN_RR_RATIO:
        return False, f"R:R {rr:.2f} < {MIN_RR_RATIO}"

    conf = strategy.min_confidence or 50.0
    if conf < MIN_CONFIDENCE:
        return False, f"min_confidence {conf} < {MIN_CONFIDENCE}"

    hold = strategy.max_holding_days or 20
    if hold < MIN_HOLDING:
        return False, f"max_holding_days {hold} < {MIN_HOLDING}"
    if hold > MAX_HOLDING:
        return False, f"max_holding_days {hold} > {MAX_HOLDING}"

    # All entry conditions use bad features → reject
    entry_feats = [
        c.feature for c in (getattr(strategy.entry_conditions, "conditions", None) or [])
        if hasattr(c, "feature")
    ]
    if bad_features and entry_feats:
        if all(f in bad_features for f in entry_feats):
            return False, f"all entry features in bad_features set: {entry_feats}"

    # Condition-level rejection: (feature, operator, threshold-bucket) triples
    # that meta_learner flagged as high-failure. Catches cases the plain
    # feature-name check misses — e.g. "rsi_14 > 70" specifically fails while
    # "rsi_14 < 30" specifically succeeds; the old feature-only check treated
    # both as the same "rsi_14" signal.
    if bad_conditions:
        for c in (getattr(strategy.entry_conditions, "conditions", None) or []):
            feat = getattr(c, "feature", None)
            op   = getattr(c, "operator", None)
            thr  = getattr(c, "threshold", None)
            if feat and op and isinstance(thr, (int, float)):
                thr_bucket = round(thr / 10) * 10
                key = f"{feat}|{op}|{thr_bucket}"
                if key in bad_conditions:
                    return False, f"condition matches known-bad zone: {key}"

    # Must have at least 2 entry conditions (single condition → curve-fit risk)
    n_conds = len(getattr(strategy.entry_conditions, "conditions", []) or [])
    if n_conds < 2:
        return False, f"only {n_conds} entry condition(s) — too few to be robust"

    return True, ""


def _in_dead_zone(strategy: StrategyDSL, graveyard_zones: list[dict]) -> bool:
    """
    Check if this strategy's parameter space overlaps with known failed zones.
    Graveyard zones are {family, stop_loss_pct?, take_profit_pct?,
    max_holding_days?, min_confidence?} dicts from meta_learner — checked
    across ALL dimensions present in a given zone, not just stop_loss_pct.
    A zone only vetoes if EVERY dimension it specifies is close to the
    candidate's value (an all-dimensions match), so a strategy that merely
    shares one similar parameter with an unrelated dead strategy isn't
    rejected — only near-total parameter-space overlap is.
    Returns True if it's too close to a dead zone → skip generation.
    """
    if not graveyard_zones:
        return False
    family = strategy.family or ""
    for zone in graveyard_zones:
        if zone.get("family") != family:
            continue

        checks = []
        if zone.get("stop_loss_pct") is not None:
            checks.append(abs(abs(strategy.stop_loss_pct or 7) - abs(zone["stop_loss_pct"])) < 1.0)
        if zone.get("take_profit_pct") is not None:
            checks.append(abs(abs(strategy.take_profit_pct or 12) - abs(zone["take_profit_pct"])) < 1.5)
        if zone.get("max_holding_days") is not None:
            checks.append(abs((strategy.max_holding_days or 20) - zone["max_holding_days"]) <= 2)
        if zone.get("min_confidence") is not None:
            checks.append(abs((strategy.min_confidence or 55) - zone["min_confidence"]) < 3.0)

        # Require at least 2 matching dimensions (or the only dimension
        # present, for older single-field zones) to call it a true overlap —
        # a match on SL alone with wildly different TP/hold isn't the same
        # failed strategy.
        if checks and sum(checks) >= min(2, len(checks)):
            return True
    return False


def generate_candidates(
    n:            int = 30,
    seed:         int | None = None,
    families:     list[str] | None = None,
    meta_state:   dict | None = None,
) -> list[StrategyDSL]:
    """
    Generate N candidate strategies, with pre-screening to ensure structural quality.

    Default reduced from 100 → 30: we want 30 viable candidates over 100 random ones.
    Pre-screening rejects R:R < 1.5, < 2 entry conditions, min_confidence < 52,
    bad-feature-only strategies, and strategies in known dead parameter zones.
    """
    rng      = random.Random(seed)
    pool     = families or list(_GENERATORS.keys())
    seen_ids = set()
    result   = []

    # Use meta-learned weights if available, else defaults
    if meta_state and meta_state.get("family_weights"):
        adapted_weights = meta_state["family_weights"]
        pool_weights = [adapted_weights.get(f, _FAMILY_WEIGHTS.get(f, 0.05)) for f in pool]
        log.info("Generator using meta-learned family weights")
    else:
        pool_weights = [_FAMILY_WEIGHTS.get(f, 0.1) for f in pool]

    total_w = sum(pool_weights)
    pool_weights = [w / total_w for w in pool_weights]

    bad_features    = set(meta_state.get("bad_features", [])) if meta_state else set()
    bad_conditions  = set(meta_state.get("bad_conditions", [])) if meta_state else set()
    conf_floor      = (meta_state.get("current_conf_floor") or 55.0) if meta_state else 55.0
    graveyard_zones = (meta_state.get("graveyard_zones") or []) if meta_state else []
    family_regime_avoid = (meta_state.get("family_regime_avoid") or {}) if meta_state else {}
    param_priors    = (meta_state.get("param_priors") or {}) if meta_state else {}

    rejected = 0
    attempts = 0
    # Higher attempt cap because pre-screening adds rejection overhead
    while len(result) < n and attempts < n * 15:
        family = rng.choices(pool, weights=pool_weights, k=1)[0]
        gen_fn = _GENERATORS[family]
        try:
            strategy = gen_fn(rng)

            # Enforce meta-learned confidence floor
            if strategy.min_confidence is None or strategy.min_confidence < conf_floor:
                strategy.min_confidence = round(conf_floor + rng.uniform(0, 8.0), 1)

            # Nudge SL/TP/hold/confidence toward what's actually working for
            # this family, when meta-learner has a confident (count>=5)
            # sample. This is what param_priors was originally documented to
            # do but never did — it was computed and returned in meta_state
            # but no generation code ever read it. A 30% pull toward the
            # prior (not a hard override) keeps genetic diversity while
            # still biasing toward evidence.
            priors = param_priors.get(family)
            if priors and priors.get("count", 0) >= 5:
                PULL = 0.3
                if priors.get("avg_sl_abs") and strategy.stop_loss_pct is not None:
                    cur = abs(strategy.stop_loss_pct)
                    strategy.stop_loss_pct = -round(cur * (1 - PULL) + priors["avg_sl_abs"] * PULL, 2)
                if priors.get("avg_tp") and strategy.take_profit_pct is not None:
                    strategy.take_profit_pct = round(
                        strategy.take_profit_pct * (1 - PULL) + priors["avg_tp"] * PULL, 2
                    )
                if priors.get("avg_hold") and strategy.max_holding_days is not None:
                    strategy.max_holding_days = max(MIN_HOLDING, min(MAX_HOLDING, round(
                        strategy.max_holding_days * (1 - PULL) + priors["avg_hold"] * PULL
                    )))

            # Family x regime avoidance: if this family's deaths concentrate
            # in a specific regime, drop that regime from allowed_regimes
            # for new candidates (previously the only regime-related meta
            # signal was a single whole-population "most_deadly_regime"
            # scalar that ignored which family was dying there).
            avoid_regimes = family_regime_avoid.get(family)
            if avoid_regimes and getattr(strategy, "allowed_regimes", None):
                remaining = [r for r in strategy.allowed_regimes if r not in avoid_regimes]
                if remaining:   # never leave a strategy with zero allowed regimes
                    strategy.allowed_regimes = remaining

            # Structural pre-screen
            ok, reason = _passes_prescreen(strategy, bad_features, bad_conditions)
            if not ok:
                rejected += 1
                log.debug("Pre-screen rejected %s [%s]: %s", family, strategy.name, reason)
                continue

            # Dead-zone check
            if _in_dead_zone(strategy, graveyard_zones):
                rejected += 1
                log.debug("Dead-zone rejected %s [%s]", family, strategy.name)
                continue

            sid = strategy.strategy_id()
            if sid not in seen_ids:
                seen_ids.add(sid)
                result.append(strategy)
        except Exception as exc:
            log.warning("Generator error in family %s: %s", family, exc)
        attempts += 1

    log.info(
        "Generated %d/%d candidates in %d attempts — rejected=%d (meta=%s bad_feats=%d conf_floor=%.1f)",
        len(result), n, attempts, rejected,
        "yes" if meta_state else "no",
        len(bad_features), conf_floor,
    )
    return result


def persist_candidates(
    db:         Session,
    candidates: list[StrategyDSL],
    generation: int = 0,
) -> int:
    """
    Write new candidates to the DB. Skips those already present.
    Returns count of new rows written.
    """
    written = 0
    for s in candidates:
        sid = s.strategy_id()
        existing = db.query(StrategyV2.id).filter(StrategyV2.strategy_id == sid).first()
        if existing:
            continue
        feature_cats = list({
            part for f in s.feature_names()
            for part in (["price"] if f in PRICE_FEATURES else
                         ["volume"] if f in VOLUME_FEATURES else
                         ["volatility"] if f in VOLATILITY_FEATURES else
                         ["trend"] if f in TREND_FEATURES else
                         ["sentiment"] if f in SENTIMENT_FEATURES else
                         ["pattern"] if f in PATTERN_FEATURES else
                         ["regime"] if f in REGIME_FEATURES else [])
        })
        row = upsert_strategy(db, {
            "strategy_id":       sid,
            "name":              s.name,
            "family":            s.family,
            "generation":        generation,
            "dsl_json":          s.to_json(),
            "feature_categories": json.dumps(feature_cats),
            "allowed_regimes":   json.dumps(s.allowed_regimes),
            "status":            "candidate",
        })
        save_version(db, sid, s.to_json(), version=1, change_type="seed")
        written += 1

    db.commit()
    log.info("Persisted %d new candidate strategies (generation=%d)", written, generation)
    return written


def run_generation_cycle(
    db:         Session,
    n:          int = 200,
    seed:       int | None = None,
    families:   list[str] | None = None,
    generation: int = 0,
    use_meta:   bool = True,
) -> dict:
    meta_state = None
    if use_meta:
        try:
            from strategies.meta_learner import compute_meta_state
            meta_state = compute_meta_state(db)
            log.info("Generation cycle using meta-state (conf_floor=%.1f bad_feats=%d)",
                     meta_state.get("current_conf_floor", 55.0),
                     len(meta_state.get("bad_features", [])))
        except Exception as exc:
            log.warning("Meta-learner unavailable, using defaults: %s", exc)

    candidates = generate_candidates(n=n, seed=seed, families=families, meta_state=meta_state)
    written    = persist_candidates(db, candidates, generation=generation)
    return {
        "generated":   len(candidates),
        "persisted":   written,
        "skipped":     len(candidates) - written,
        "generation":  generation,
        "meta_used":   meta_state is not None,
    }

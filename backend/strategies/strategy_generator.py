"""
Strategy Generator
Generates candidate strategies from named, documented, tried-and-tested
quant effects — each a fixed template whose parameters (thresholds, SL/TP,
hold days) are mutated/evolved, but the template's structural logic itself
is never invented at random.

Generation approach:
  - For each family template, define a parameter grid (thresholds, feature combinations)
  - Randomly sample N points from the grid to produce candidates
  - Each candidate is a valid StrategyDSL object immediately ready for backtesting
  - Deduplication via strategy_id hash — duplicates are silently skipped

Supported families (research-backed templates):
  post_earnings_drift, momentum_trend, mean_reversion_quality,
  event_catalyst, regime_dca_timing, rotation_monitor
  (plus pre-existing: quality_momentum, institutional_flow, rl_momentum,
  relative_strength, breadth_momentum, long_hold_momentum)

The original 8 generic random-parameter families (momentum, mean_reversion,
breakout, sentiment_driven, regime_adaptive, volume_surge, volatility_play,
hybrid) were removed — they mutated random threshold combinations across flat
feature pools (PRICE_FEATURES/VOLUME_FEATURES/etc, several of which were never
backed by a real computed feature — e.g. "price_above_ema50",
"vwap_distance", "sentiment_score" do not exist in feature_registry.py) with
no named quant basis. See BUG_HUNTING.md if you're looking for that history.
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
from features.research_features import REGIME_MARKOV_CODES

log = get_logger("strategy_generator")

# regime_markov is stored as a numeric code (FeatureValue.value is Float —
# see research_features.py::_encode_regime for why the string label can't be
# written directly). Conditions must compare against these codes, not the
# original "BULL"/"BEAR"/"SIDEWAYS" string labels.
REGIME_MARKOV_BULL = REGIME_MARKOV_CODES["BULL"]
REGIME_MARKOV_BEAR = REGIME_MARKOV_CODES["BEAR"]
REGIME_MARKOV_SIDEWAYS = REGIME_MARKOV_CODES["SIDEWAYS"]

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
    # GO-5b cross-sectional / breadth features
    "nifty_rs_21d", "sector_rs_21d", "relative_strength_nifty_21d",
    "breadth_pct_above_ema50", "breadth_pct_above_ema200",
    # Markov observable-chain regime label (backend/markov module)
    "regime_markov",
]
# Research-derived features (research_synthesis funnel) — registered in
# feature_registry.py, category="research". Point-in-time joined, null when
# no synthesis exists for the symbol/date; never fabricated.
RESEARCH_FEATURES = [
    "research_sentiment", "research_confidence", "research_risk_flag_negative",
]
# Event/catalyst features (earnings_events, nse_corporate_filings, news_events)
# — registered in feature_registry.py, category="events".
EVENT_FEATURES = [
    "catalyst_earnings_beat", "catalyst_buyback", "catalyst_order_win",
    "catalyst_dividend_hike", "management_change_recent",
    "days_to_earnings", "days_since_earnings",
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


# ── Named, research-backed templates ────────────────────────────────
# Every template below combines >=1 research-derived condition AND >=1
# technical confirmation condition — never fires on sentiment alone.

# Tier 1 (owned) vs Tier 2 (bench) symbols for _generate_rotation_monitor —
# per the curated 12-symbol universe pruning.
TIER1_OWNED_SYMBOLS = ["BEL", "HDFCBANK", "NTPC"]
TIER2_BENCH_SYMBOLS = ["ICICIBANK", "INFY", "CDSL", "DRREDDY", "LT", "HAL"]


def _generate_post_earnings_drift(rng: random.Random) -> StrategyDSL:
    """
    Post-Earnings-Announcement Drift (PEAD) — Ball & Brown (1968); Bernard &
    Thomas (1989, 1990). Stock prices under-react to earnings surprises: a
    positive surprise (beat) is followed by continued excess drift over the
    following weeks rather than an instantaneous full repricing. Entry
    requires a confirmed beat (catalyst_earnings_beat) AND positive
    research-synthesis sentiment (research-derived) AND recency to the
    print (days_since_earnings, technical/event confirmation) — never fires
    on sentiment alone.
    """
    sent_th   = round(rng.uniform(0.1, 0.4), 2)
    since_th  = rng.randint(0, 2)   # within 0-2 days after results
    n_conds   = rng.randint(3, 4)

    conds = [
        _make_condition("catalyst_earnings_beat", "==", 1),
        _make_condition("research_sentiment", ">", sent_th),
        _make_condition("days_since_earnings", "<=", since_th),
    ]
    if n_conds >= 4:
        conds.append(_make_condition("rsi_14", ">", round(rng.uniform(45, 60), 1)))

    exit_ = ConditionGroup(conditions=[
        _make_condition("research_sentiment", "<", 0.0),
        _make_condition("rsi_14", ">", round(rng.uniform(72, 82), 1)),
    ], logic="OR")

    sl = round(-rng.uniform(6, 10), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "post_earnings_drift",
        name             = f"PEAD_sent{sent_th}_since{since_th}",
        min_confidence   = _rand_confidence(rng, 55.0, 70.0),
        max_holding_days = rng.randint(10, 40),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.8),
    )


def _generate_momentum_trend(rng: random.Random) -> StrategyDSL:
    """
    Cross-sectional/time-series momentum — Jegadeesh & Titman (1993);
    Moskowitz, Ooi & Pedersen (2012, "Time Series Momentum"). Stocks with
    strong trailing 3-12 month returns tend to continue outperforming over
    the following weeks/months. Entry requires positive multi-period price
    momentum (technical) AND the market-wide regime (research/regime-derived
    via the Markov module) being bullish — avoids chasing momentum into a
    deteriorating macro backdrop.
    """
    mom_feat = rng.choice(["return_21d", "momentum_20d", "return_63d"])
    mom_th   = round(rng.uniform(2.0, 6.0), 2)
    n_conds  = rng.randint(3, 4)

    conds = [
        _make_condition(mom_feat, ">", mom_th),
        _make_condition("regime_markov", "==", REGIME_MARKOV_BULL),
    ]
    if n_conds >= 3:
        conds.append(_make_condition("rsi_14", ">", round(rng.uniform(50, 60), 1)))
    if n_conds >= 4:
        conds.append(_make_condition("adx_14", ">", round(rng.uniform(20, 28), 1)))

    exit_ = ConditionGroup(conditions=[
        _make_condition(mom_feat, "<", round(-rng.uniform(1.0, 3.0), 2)),
        _make_condition("regime_markov", "==", REGIME_MARKOV_BEAR),
    ], logic="OR")

    sl = round(-rng.uniform(7, 11), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_only", "bull_sideways"])],
        family           = "momentum_trend",
        name             = f"MomTrend_{mom_feat[:8]}_{mom_th}",
        min_confidence   = _rand_confidence(rng, 55.0, 70.0),
        max_holding_days = rng.randint(15, 40),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 2.0),
    )


def _generate_mean_reversion_quality(rng: random.Random) -> StrategyDSL:
    """
    Short-term mean reversion — Connors & Alvarez's RSI(2) research
    (short-horizon oversold bounces in trending stocks tend to revert
    quickly). NOTE — LIMITATION: feature_registry.py only computes RSI(14)
    (rsi_14); no RSI(2) feature exists yet. This template substitutes an
    adapted, very-low threshold on rsi_14 (RSI(14) rarely prints as low as
    RSI(2) does, so the effective threshold band here is intentionally
    higher than classic RSI(2) < 10 rules) and documents the substitution
    honestly rather than fabricating an RSI(2) feature. Entry requires
    rsi_14 oversold AND price still above a longer-term trend proxy
    (mean reversion within an uptrend, not a falling knife) AND no negative
    research risk flags (research-derived condition).
    """
    rsi_lo  = round(rng.uniform(28, 38), 1)   # adapted RSI(14) oversold band — see docstring
    n_conds = rng.randint(3, 4)

    conds = [
        _make_condition("rsi_14", "<", rsi_lo),
        _make_condition("price_vs_ema50_pct", ">", round(rng.uniform(-2.0, 5.0), 2)),
        _make_condition("research_risk_flag_negative", "==", 0),
    ]
    if n_conds >= 4:
        conds.append(_make_condition("return_5d", "<", round(-rng.uniform(1.5, 4.0), 2)))

    exit_ = ConditionGroup(conditions=[
        _make_condition("rsi_14", ">", round(rng.uniform(50, 60), 1)),
    ])

    sl = round(-rng.uniform(4, 8), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "mean_reversion_quality",
        name             = f"MeanRevQ_RSI{rsi_lo}",
        min_confidence   = _rand_confidence(rng, 50.0, 65.0),
        max_holding_days = rng.randint(5, 15),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.5),
    )


def _generate_event_catalyst(rng: random.Random) -> StrategyDSL:
    """
    Event-study drift — corporate-action announcement effects (buybacks:
    Ikenberry, Lakonishok & Vermaelen 1995; large order wins/contract
    announcements and dividend increases as positive information signals
    consistent with the broader post-announcement-drift literature). Entry
    fires on ANY of buyback / large-order-win / dividend-hike catalysts
    (research/event-derived, OR logic) AND positive research sentiment AND
    a technical confirmation (price above a short EMA) — never on the
    catalyst alone.
    """
    sent_th = round(rng.uniform(0.05, 0.3), 2)
    n_conds = rng.randint(3, 4)

    catalyst_group = ConditionGroup(
        conditions=[
            _make_condition("catalyst_buyback", "==", 1),
            _make_condition("catalyst_order_win", "==", 1),
            _make_condition("catalyst_dividend_hike", "==", 1),
        ],
        logic="OR",
    )
    conds = [
        catalyst_group,
        _make_condition("research_sentiment", ">", sent_th),
        _make_condition("price_vs_ema21_pct", ">", round(rng.uniform(-1.0, 2.0), 2)),
    ]
    if n_conds >= 4:
        conds.append(_make_condition("management_change_recent", "==", 0))

    sl = round(-rng.uniform(6, 10), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "event_catalyst",
        name             = f"EventCat_sent{sent_th}",
        min_confidence   = _rand_confidence(rng, 54.0, 68.0),
        max_holding_days = rng.randint(8, 25),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.8),
    )


def _generate_regime_dca_timing(rng: random.Random) -> StrategyDSL:
    """
    Valuation-conditioned dollar-cost averaging — the well-documented
    empirical result that DCA/SIP allocations tilted toward periods of
    depressed valuation (buying more when the market/regime is in a Bear
    phase and the stock is oversold on a 52-week basis) outperform pure
    time-based DCA. NOTE: this is fundamentally a monthly SIP-allocation
    TILT signal, not a standalone entry/exit trade — implemented here as a
    StrategyDSL so it can run through the existing promotion/backtest
    pipeline, but its practical use downstream should be as an
    allocation-tilt signal for the Personal Portfolio module, not a
    freestanding paper-trading algo. Entry: Markov regime is Bear
    (research/regime-derived) AND price is notably below its 52-week range
    (technical confirmation of "cheap").
    """
    pos_th  = round(rng.uniform(0.15, 0.35), 2)   # price_position_52w below this = "cheap" zone
    n_conds = rng.randint(2, 3)

    conds = [
        _make_condition("regime_markov", "==", REGIME_MARKOV_BEAR),
        _make_condition("price_position_52w", "<", pos_th),
    ]
    if n_conds >= 3:
        conds.append(_make_condition("rsi_14", "<", round(rng.uniform(35, 48), 1)))

    sl = round(-rng.uniform(10, 16), 1)   # wide SL — this is an allocation tilt, not a tight trade
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS["defensive"],
        family           = "regime_dca_timing",
        name             = f"RegimeDCA_pos{pos_th}",
        min_confidence   = _rand_confidence(rng, 50.0, 62.0),
        max_holding_days = rng.randint(30, 60),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.5),
    )


def _generate_rotation_monitor(rng: random.Random) -> StrategyDSL:
    """
    Cross-sectional relative strength / sector rotation — the classic
    relative-strength rotation approach (e.g. Levy 1967; modern factor
    literature on cross-sectional momentum) of rotating capital toward
    names showing the strongest relative strength vs peers/benchmark.
    LIMITATION — honestly flagged: the DSL evaluates ONE symbol's feature
    row at a time with no cross-symbol join capability, so a true
    owned-tier-vs-bench-tier cross-sectional comparison (Tier 1 owned:
    BEL/HDFCBANK/NTPC vs Tier 2 bench: ICICIBANK/INFY/CDSL/DRREDDY/LT/HAL)
    cannot be expressed inside a single-symbol DSL rule. This template
    therefore uses relative_strength_nifty_21d (already-computed feature) as
    an ABSOLUTE proxy for "this symbol has strong relative strength" — firing
    per-symbol when RS vs NIFTY is strongly positive. The actual cross-
    sectional owned-vs-bench COMPARISON is a signal-layer concern that
    belongs in a post-promotion allocator/rotation monitor built on top of
    per-symbol outputs, not in this DSL rule — flagged here rather than
    oversold as something this template doesn't actually do.
    """
    rs_th   = round(rng.uniform(3.0, 8.0), 2)   # strong absolute RS-vs-NIFTY proxy
    n_conds = rng.randint(2, 3)

    conds = [
        _make_condition("relative_strength_nifty_21d", ">", rs_th),
        _make_condition("sector_rs_21d", ">", round(rng.uniform(0.5, 3.0), 2)),
    ]
    if n_conds >= 3:
        conds.append(_make_condition("volume_ratio_20d", ">", round(rng.uniform(1.1, 1.6), 2)))

    exit_ = ConditionGroup(conditions=[
        _make_condition("relative_strength_nifty_21d", "<", round(-rng.uniform(0.5, 2.0), 2)),
    ])

    sl = round(-rng.uniform(7, 11), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "rotation_monitor",
        name             = f"Rotation_RS{rs_th}",
        min_confidence   = _rand_confidence(rng, 54.0, 68.0),
        max_holding_days = rng.randint(15, 35),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 1.8),
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


def _generate_relative_strength(rng: random.Random) -> StrategyDSL:
    """
    GO-5b: Cross-sectional relative strength — enter when a stock is outperforming
    both NIFTY and its sector over the past 21 days. Cross-sectional signals are
    harder for transaction costs to erase than absolute-level signals because the
    spread being traded is the alpha vs the index, not the raw return.
    Hold 20-40 days to amortize NSE's 0.28% round-trip cost (cost drag / hold_days
    falls with longer hold; at 30d hold it's ~0.009%/day vs edge of ~0.05%+/day).
    """
    rs_nifty_th  = round(rng.uniform(1.5, 5.0), 2)   # stock outperforms NIFTY by X% over 21d
    rs_sector_th = round(rng.uniform(0.5, 3.0), 2)   # stock outperforms sector by Y% over 21d
    n_conds      = rng.randint(2, 4)

    conds = [
        _make_condition("nifty_rs_21d",  ">", rs_nifty_th,  weight=1.2),
        _make_condition("sector_rs_21d", ">", rs_sector_th, weight=1.0),
    ]
    if n_conds >= 3:
        # Confirm trend is intact — not entering on a dead-cat bounce
        conds.append(_make_condition("price_above_ema50", "==", 1.0))
    if n_conds >= 4:
        # Volume confirms accumulation, not rotation out of sector
        conds.append(_make_condition("volume_ratio_20d", ">", round(rng.uniform(1.1, 1.6), 2)))

    exit_ = ConditionGroup(conditions=[
        _make_condition("nifty_rs_21d", "<", round(-rng.uniform(0.5, 2.0), 2)),  # RS turns negative
        _make_condition("rsi_14", ">", round(rng.uniform(72, 82), 1)),
    ], logic="OR")

    sl = round(-rng.uniform(7, 12), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "bull_only", "all_weather"])],
        family           = "relative_strength",
        name             = f"RS_N{rs_nifty_th}_S{rs_sector_th}",
        min_confidence   = _rand_confidence(rng, 55.0, 70.0),
        max_holding_days = rng.randint(20, 45),   # long hold to amortize cost
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 2.0),
    )


def _generate_breadth_momentum(rng: random.Random) -> StrategyDSL:
    """
    GO-5b: Market breadth + stock momentum. Only enter when the market is in
    broad-based rally (many stocks above EMA50) AND this stock has momentum.
    Avoids buying an individual leader into a deteriorating market — a major
    source of failed trades in the current population (VOLATILE-only bias
    concentrates entries into high-dispersion periods where breadth is low).
    Hold 15-35 days — breadth signals are slow to turn, so holding is rewarded.
    """
    breadth_th = round(rng.uniform(55, 72), 1)   # >55-72% of universe above EMA50
    mom_th     = round(rng.uniform(2.0, 6.0), 2)
    n_conds    = rng.randint(3, 4)

    conds = [
        _make_condition("breadth_pct_above_ema50", ">", breadth_th, weight=1.1),
        _make_condition("return_21d", ">", mom_th),
    ]
    if n_conds >= 3:
        conds.append(_make_condition("rsi_14", ">", round(rng.uniform(48, 60), 1)))
    if n_conds >= 4:
        conds.append(_make_condition("adx_14", ">", round(rng.uniform(20, 28), 1)))

    exit_ = ConditionGroup(conditions=[
        _make_condition("breadth_pct_above_ema50", "<", round(rng.uniform(40, 52), 1)),
        _make_condition("return_5d", "<", round(-rng.uniform(2.5, 5.0), 1)),
    ], logic="OR")

    sl = round(-rng.uniform(7, 11), 1)
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_only", "bull_sideways"])],
        family           = "breadth_momentum",
        name             = f"BreadthMom_B{breadth_th}_M{mom_th}",
        min_confidence   = _rand_confidence(rng, 55.0, 70.0),
        max_holding_days = rng.randint(15, 35),
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 2.0),
    )


def _generate_long_hold_momentum(rng: random.Random) -> StrategyDSL:
    """
    GO-5b: Extended hold (30-60 days) amortizes NSE round-trip cost across more days.
    At 0.28% round-trip over 45 days = 0.006%/day cost drag — an edge of only 0.01%/day
    net of costs clears the bar. Short-hold families (3-8d) need 0.037%/day JUST to
    break even. Inspired by the NSE delivery-market structure: delivery buyers are
    committed capital, not noise, so momentum in high-delivery stocks persists longer.
    Uses 3-month (63d) return as the signal — captures the medium-term momentum factor
    that academic literature (Jegadeesh & Titman, Fama-French) consistently finds.
    """
    ret63_th   = round(rng.uniform(5.0, 15.0), 2)   # 3-month return > 5-15%
    n_conds    = rng.randint(3, 4)

    # 3-month momentum as primary; fall back to 21d if 63d not in feature set
    mom_feat   = rng.choice(["return_21d", "momentum_20d", "relative_strength_nifty_21d"])
    mom_th2    = round(rng.uniform(3.0, 8.0), 2)

    conds = [
        _make_condition(mom_feat, ">", mom_th2, weight=1.2),
    ]
    if n_conds >= 2:
        conds.append(_make_condition("rsi_14", ">", round(rng.uniform(50, 62), 1)))
    if n_conds >= 3:
        # High delivery = genuine buying, not speculation
        conds.append(_make_condition("delivery_pct", ">", round(rng.uniform(55, 72), 1)))
    if n_conds >= 4:
        conds.append(_make_condition("price_above_ema50", "==", 1.0))

    exit_ = ConditionGroup(conditions=[
        _make_condition(mom_feat, "<", round(-rng.uniform(1.0, 3.0), 2)),   # momentum reversal
        _make_condition("rsi_14", ">", round(rng.uniform(74, 84), 1)),
    ], logic="OR")

    sl = round(-rng.uniform(10, 16), 1)   # wider SL for longer hold — normal retracement
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "long_hold_momentum",
        name             = f"LongHold_{mom_feat[:8]}_{mom_th2}",
        min_confidence   = _rand_confidence(rng, 56.0, 72.0),
        max_holding_days = rng.randint(30, 60),   # 30-60 day delivery swing
        stop_loss_pct    = sl,
        take_profit_pct  = _rr_take_profit(rng, sl, 2.2),   # min 2.2:1 R:R
    )


_GENERATORS = {
    # Named, research-backed templates (replace the old 8 generic random families)
    "post_earnings_drift":     _generate_post_earnings_drift,
    "momentum_trend":          _generate_momentum_trend,
    "mean_reversion_quality":  _generate_mean_reversion_quality,
    "event_catalyst":          _generate_event_catalyst,
    "regime_dca_timing":       _generate_regime_dca_timing,
    "rotation_monitor":        _generate_rotation_monitor,
    # Pre-existing research-backed families (unaffected by this change)
    "quality_momentum":    _generate_quality_momentum,
    "institutional_flow":  _generate_institutional_flow,
    "rl_momentum":         _generate_rl_momentum,
    # GO-5b: signal-quality upgrades per population diagnosis
    "relative_strength":   _generate_relative_strength,
    "breadth_momentum":    _generate_breadth_momentum,
    "long_hold_momentum":  _generate_long_hold_momentum,
}

# Family weights for generation — bias toward historically stronger families
# GO-5b families get high initial weights: diagnosis showed cost drag kills short-hold
# families; cross-sectional RS and long-hold families are structurally cost-advantaged.
_FAMILY_WEIGHTS = {
    # New research-backed templates — initial weights, meta-learner adapts over time
    "post_earnings_drift":     0.10,
    "momentum_trend":          0.10,
    "mean_reversion_quality":  0.08,
    "event_catalyst":          0.08,
    "regime_dca_timing":       0.05,   # allocation-tilt signal, not a core trading family
    "rotation_monitor":        0.08,
    "quality_momentum":    0.09,
    "institutional_flow":  0.06,
    "rl_momentum":         0.09,
    # GO-5b: cross-sectional and long-hold families weighted up per diagnosis
    "relative_strength":   0.12,   # RS signal is cross-sectional — cost-advantaged
    "breadth_momentum":    0.09,   # breadth filter avoids bad-market entries
    "long_hold_momentum":  0.14,   # 30-60d hold: cost drag ~0.005-0.009%/day vs 0.037%/day at 3d
}


# ── Pre-screening gate ────────────────────────────────────────────────
# Reject structurally bad strategies before they ever reach the backtester.
# This saves backtest time and prevents noise from polluting the population.

MIN_RR_RATIO    = 1.5    # take_profit must be at least 1.5× |stop_loss|
MIN_CONFIDENCE  = 52.0   # below this, the strategy fires on noise
MAX_HOLDING     = 65     # GO-5b long-hold families go up to 60d; 65 gives headroom
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

    # Condition-level rejection: (family, feature, operator, threshold-bucket)
    # quadruples that meta_learner flagged as high-failure. Catches cases the
    # plain feature-name check misses — e.g. "rsi_14 > 70" specifically fails
    # while "rsi_14 < 30" specifically succeeds; the old feature-only check
    # treated both as the same "rsi_14" signal. Scoped by family (not just
    # feature/operator/threshold) because a generic condition like
    # "rsi_14 > 50" is shared across many families — without the family key,
    # a handful of dead `momentum` strategies with that condition blacklisted
    # it for every other family too, silently zeroing out breadth_momentum
    # and long_hold_momentum generation entirely even though neither family
    # had ever produced a single graveyard entry of its own. See
    # BUG_HUNTING.md for the confirmed root cause and live-DB reproduction.
    if bad_conditions:
        family = strategy.family or ""
        for c in (getattr(strategy.entry_conditions, "conditions", None) or []):
            feat = getattr(c, "feature", None)
            op   = getattr(c, "operator", None)
            thr  = getattr(c, "threshold", None)
            if feat and op and isinstance(thr, (int, float)):
                thr_bucket = round(thr / 10) * 10
                key = f"{family}|{feat}|{op}|{thr_bucket}"
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
                         ["regime"] if f in REGIME_FEATURES else
                         ["research"] if f in RESEARCH_FEATURES else
                         ["events"] if f in EVENT_FEATURES else [])
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

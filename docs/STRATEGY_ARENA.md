# AQRTI Strategy Arena — Complete Reference

> Last updated: 2026-07-01  
> Covers: Strategy Generation → Backtesting → Fitness Scoring → Lifecycle → Evolution → Meta-Learning → Self-Learning  

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Strategy DSL](#3-strategy-dsl)
4. [Strategy Generator](#4-strategy-generator)
5. [Backtester](#5-backtester)
6. [Fitness Engine](#6-fitness-engine)
7. [Lifecycle Manager](#7-lifecycle-manager)
8. [Evolution Engine](#8-evolution-engine)
9. [Meta-Learner](#9-meta-learner)
10. [Daily Research Loop](#10-daily-research-loop)
11. [Self-Learning System](#11-self-learning-system)
12. [ML Models & Prediction Pipeline](#12-ml-models--prediction-pipeline)
13. [Key Constants Reference](#13-key-constants-reference)
14. [Data Flow & Timing](#14-data-flow--timing)
15. [Known Issues & Design Decisions](#15-known-issues--design-decisions)

---

## 1. System Overview

The Strategy Arena is a closed-loop genetic algorithm system that:

1. **Generates** candidate trading strategies from DSL templates (10 families)
2. **Backtests** each candidate against 3 years of 50-stock NSE price history
3. **Scores** each strategy with a 6-dimension composite Fitness Score (0-100)
4. **Promotes** winners, **retires** losers via a state machine
5. **Evolves** the population through mutation and crossover of top parents
6. **Learns** from failures (model drift, prediction errors, live trade outcomes)
7. **Adapts** generation weights, mutation preferences, and confidence floors automatically

No human intervention is required. Human approval is required only to move a strategy to `active` status for real capital deployment.

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     DAILY RESEARCH LOOP                         │
│  (runs every 5min via APScheduler, triggered at boot sequence)  │
│                                                                 │
│  ┌──────────────┐    ┌────────────────┐    ┌────────────────┐  │
│  │  GENERATOR   │───▶│   BACKTESTER   │───▶│ FITNESS ENGINE │  │
│  │  50 new/day  │    │  3yr / 50 stk  │    │  0-100 score   │  │
│  └──────────────┘    └────────────────┘    └───────┬────────┘  │
│                                                    │            │
│  ┌──────────────────────────────────────────────────▼────────┐  │
│  │                    LIFECYCLE MANAGER                       │  │
│  │  candidate → shadow → promoted → [active] → retired       │  │
│  └──────────────────────────────┬───────────────────────────┘  │
│                                 │                               │
│  ┌──────────────────────────────▼───────────────────────────┐  │
│  │                   EVOLUTION ENGINE                         │  │
│  │  Tournament select → Mutate/Crossover → Backtest → Score   │  │
│  └──────────────────────────────┬───────────────────────────┘  │
│                                 │                               │
│  ┌──────────────────────────────▼───────────────────────────┐  │
│  │                    META-LEARNER                            │  │
│  │  Reads graveyard + evolution history + live trades        │  │
│  │  Adjusts: family weights, bad features, conf floor        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    DAILY LEARNING LOOP                          │
│  (runs daily, triggered by boot sequence and APScheduler)       │
│                                                                 │
│  Step 0: Backfill prediction outcomes from price data           │
│  Step 1: Evaluate pending pattern outcomes                      │
│  Step 2: Failure analysis (detect → classify → root cause)      │
│  Step 3: Model drift detection (7d + 30d + 90d windows)         │
│  Step 3B: Auto-retrain if 30d drift flagged                     │
│  Step 4: Confidence scaling recommendation                      │
│  Step 5: Feature decay detection (IC by rolling window)         │
│  Step 6: Pattern memory sync                                    │
│  Step 7: Daily knowledge score (0-100 Intelligence Score)       │
│  Step 8: Log KnowledgeEvent summary                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Strategy DSL

**File:** `backend/strategies/strategy_dsl.py`

Every strategy is stored as a `StrategyDSL` object serialised to JSON in `strategies_v2.dsl_json`.

### DSL Fields

| Field | Type | Description |
|---|---|---|
| `name` | str | Human-readable name |
| `family` | str | One of 10 strategy families |
| `entry_conditions` | ConditionGroup | Tree of Condition nodes (AND/OR logic) |
| `allowed_regimes` | list[str] | Which market regimes allow entry |
| `min_confidence` | float | ML confidence gate (45–85%) |
| `stop_loss_pct` | float | Stop loss (negative, e.g. -3.0 = 3% stop) |
| `take_profit_pct` | float | Take profit target |
| `max_holding_days` | int | Force-close after this many days |

### Condition Structure

```python
Condition(feature="rsi_14", operator=">", threshold=55.0, weight=1.0)
```

Operators: `>`, `>=`, `<`, `<=`  
Features come from the feature registry (price, volume, volatility, trend, sentiment, pattern, regime).

### Strategy ID

The `strategy_id` is a SHA-256 hash of the DSL JSON — guarantees deduplication across the whole population.

---

## 4. Strategy Generator

**File:** `backend/strategies/strategy_generator.py`

### Feature Pools

| Category | Features |
|---|---|
| Price | return_1d, return_5d, return_21d, momentum_10d, momentum_20d, breakout_distance_52w, price_position_52w, relative_strength_nifty_21d, support_distance_20d, resistance_distance_20d |
| Volume | volume_ratio_20d, delivery_pct, volume_surge_flag, vwap_distance, institutional_flow_proxy |
| Volatility | atr_14, bb_width_20, realized_vol_20d, vol_ratio_short_long, hv_percentile_252d |
| Trend | ema_20, ema_50, macd_signal, adx_14, rsi_14, stoch_k, price_above_ema50, ema20_above_ema50 |
| Sentiment | sentiment_score, sentiment_velocity, news_impact_score, sector_sentiment_score |
| Pattern | pattern_confidence, similarity_score |
| Regime | regime_confidence, breadth_pct, nifty_trend_score |

### Strategy Families

| Family | Focus | Default Weight |
|---|---|---|
| momentum | Price momentum over 5-21d | 18% |
| mean_reversion | Oversold RSI / EMA bounce | 10% |
| breakout | 52-week high breakouts | 12% |
| sentiment_driven | News + sentiment score entry | 6% |
| regime_adaptive | Regime-aware multi-condition | 8% |
| volume_surge | Volume spike + price movement | 10% |
| volatility_play | ATR / BB width entries | 8% |
| hybrid | Mixed feature categories | 8% |
| quality_momentum | Momentum + delivery + trend | 12% |
| institutional_flow | Institutional flow proxy | 8% |

Meta-learning adjusts these weights dynamically based on graveyard analysis and live performance. Range: 2%–35%.

### Generation per Cycle

- **50 new candidates/day** (raised from 30 after 50-stock universe expansion)
- Each candidate immediately pre-screened (`_passes_prescreen`) before backtesting
- Pre-screen rejects structurally invalid DSLs (no conditions, bad feature names, known bad features from meta-learner)

---

## 5. Backtester

**File:** `backend/strategies/strategy_backtester.py`

### Transaction Cost Model

| Market | Brokerage | STT | SEBI/Stamp | Slippage | Round-trip |
|---|---|---|---|---|---|
| NSE (delivery) | 0.03% buy + 0.03% sell | 0.1% sell only | 0.015% + 0.015% | 0.05% | ~0.28% |
| US (IBKR-style) | 0.005/sh | — | — | 0.05% | ~0.10% |
| LSE | 0.10% + 0.5% stamp | — | — | 0.07% | ~0.77% |

All backtests for strategy evaluation use the NSE cost model.

### Backtest Configuration

| Setting | Value | Rationale |
|---|---|---|
| Backtest period | 5 years (1825 days) — widened from 3yr/1095 days as of the 2026-07-02 Trust Overhaul | Matches the full 5yr price history now available |
| Universe | All active stocks with ≥50 price rows, restricted to symbols with average daily turnover ≥ ₹5cr (2026-07-02b) | DB-dynamic; excludes illiquid names that give fills a real order could never get |
| Position size | 5% of portfolio per trade | Limits single-stock risk |
| Max open trades | 8 concurrent | Limits total exposure to 40% |
| Confidence gate | Per-strategy `min_confidence` (45–85%) | ML must agree before entry |

### Signal Generation

1. Load ML predictions for the symbol on that date
2. Load regime (BULL/BEAR/SIDEWAYS/VOLATILE) — only trade if regime is in `allowed_regimes`
3. Evaluate entry `Condition` tree against feature store values
4. Check `confidence >= min_confidence`
5. If all pass → open position; else skip

### Walk-Forward Out-of-Sample Check

After in-sample backtest, a 20% out-of-sample slice is held back. If OOS Sharpe < IS Sharpe × 0.4, the strategy is flagged as overfit and scored with a 30% penalty. This prevents strategies that memorised the training period from being promoted.

### Key Output Metrics

`BacktestResult` contains:
- `sharpe`, `sortino`, `win_rate`, `profit_factor`, `max_drawdown`, `expectancy`
- `trade_count`, `avg_holding_days`, `exposure_pct`
- `bull_sharpe`, `bear_sharpe`, `sideways_sharpe`, `volatile_sharpe`

---

## 6. Fitness Engine

**File:** `backend/strategies/fitness_engine.py`

### Composite Score (0-100)

```
fitness = 0.28 × Profitability
        + 0.22 × Consistency
        + 0.18 × Robustness
        + 0.15 × CostEfficiency
        + 0.12 × RegimeAdaptability
        + 0.05 × Longevity
```

### Dimension Details

**Profitability (28%)**
- Sharpe (45 pts): 0 at Sharpe=0, full at Sharpe≥1.2
- Profit Factor (35 pts): 0 at PF=1.0, full at PF≥2.0
- Total Return (20 pts): full at ≥25% total return

**Consistency (22%)**
- Win Rate (60 pts): full at ≥52%
- Expectancy (40 pts): full at ≥2.0% avg per trade

**Robustness (18%)**
- Regime Breadth (40 pts): how many regimes are positive Sharpe
- Max Drawdown (40 pts): full at MDD=0%, 0 at MDD≥20%
- Overall Sharpe (20 pts): same as profitability
- Walk-forward penalty: if avg_holding_days < 3 → ×0.5 (cost drag makes short-hold unlivable)

**Cost Efficiency (15%)**
- Net expectancy = expectancy − 0.05% live buffer
- Base (70 pts): scales with net expectancy / 2.0%
- Frequency bonus (30 pts): +30 if hold≥10d, +20 if hold≥5d, +10 if hold≥3d
- Hard zero if trade_count < 10 or net expectancy < 0

**Regime Adaptability (12%)**
- Score = current regime's Sharpe / 1.2 × 100
- Rewards strategies that are strong in the current market environment

**Longevity (5%)**
- 0 below 10 trades
- Grades from 10 to 100 trades (full at 100+)

### Thresholds Changed (2026-07-01)

| Constant | Old | New | Reason |
|---|---|---|---|
| `MIN_TRADES` | 500 | 10 | 500 was unreachable with 3yr NSE data; max observed = ~430 |
| `TARGET_TRADES` | 500 | 100 | Calibrated to realistic 3yr × 50-stock signal frequency |
| `LIVE_BUFFER_PCT` | 0.10% | 0.05% | Backtester already models NSE costs accurately; 10bp buffer was too punishing |

---

## 7. Lifecycle Manager

> ⚠️ **Gate constants live in `backend/strategies/promotion_config.py` — that
> file is the single source of truth. If this document ever disagrees with
> it, the config wins.** (This section was found out of sync with the code
> during the 2026-07-05 docs review — see `IMPROVEMENTS.md` P1-7 — and has
> been corrected below.)

**File:** `backend/strategies/strategy_lifecycle.py`

### State Machine

```
candidate ──▶ shadow ──▶ promoted ──▶ [active]* ──▶ retired
                │                                       ▲
                └───────────────────────────────────────┘
                         (fitness drops below gate)

* active requires human approval AND a paper-trading quarantine period
  (see Quarantine Gate below) — AQRTI never auto-promotes to 'active'.
```

### Promotion Gates (ALL must pass)

| Gate | Threshold | Notes |
|---|---|---|
| `fitness_score` | ≥ 50.0 | Composite 0-100 score |
| `trade_count` | ≥ 60 | Was 300 (unreachable — empirical max ~430, average ~52 over the in-sample window) and briefly 10 (statistical noise) before settling at 60, which gives a ±6pp 95% CI on win-rate |
| `win_rate` | ≥ 52% | Must beat coin-flip with margin |
| `sharpe` | ≥ 0.5 | Honest daily mark-to-market Sharpe (post-2026-07 backtester fix) — NOT the old inflated per-trade-repeat scale; recalibrate against the population distribution after each full re-score |
| OOS pass | required | Must pass a hard out-of-sample gate on a held-out, embargoed 6-month walk-forward window (`MIN_OOS_SHARPE=0.2`) — added 2026-07-02, this is what actually proves a strategy generalizes rather than curve-fits |
| Benchmark gate | Sharpe ≥ 0.8× buy-and-hold NIFTY50 Sharpe (same window) | A strategy that can't beat "do nothing" isn't worth capital |
| Duplicate gate | backtest-trade overlap with any already-promoted strategy ≤ 60% Jaccard on (symbol, entry_date) | Near-clones add concentration risk, not diversification |

### Retirement Triggers

| Trigger | Threshold |
|---|---|
| `fitness_score` | < 15.0 |
| `win_rate` (promoted only) | < 52% |
| `max_drawdown` | < −35% on the honest daily mark-to-market series (added 2026-07-03 — the previous limit was a hardcoded `-100.0`, effectively unreachable, meaning a strategy could carry a catastrophic real drawdown and never be retired for it as long as fitness/win-rate/Sharpe still looked fine) |

Retired strategies are **never deleted** — they go to `StrategyGraveyard` with lessons extracted. The graveyard feeds the Meta-Learner.

### Quarantine Gate on `promoted → active` (added 2026-07-02b)
Even after clearing every promotion gate above, human approval to `active`
status is **blocked** until the strategy has been sitting in `promoted`
status for at least `QUARANTINE_MIN_DAYS=60` calendar days **and** has
produced at least `QUARANTINE_MIN_TRADES=20` closed forward-paper (shadow)
trades with a win rate ≥ `QUARANTINE_MIN_WIN_RATE=50%` and positive net P&L
on those trades. This is forward performance on data that genuinely did not
exist when the strategy was created — the one validation step that cannot
be overfit by construction. `force=true` can override it on the `/activate`
endpoint, but the override is logged.

### Live Performance Adjustment

After lifecycle sweep, paper trading results are read back:
- ≥5 live closed trades AND live win_rate > backtest + 5pp → **+up to 5 pts** fitness boost
- ≥5 live closed trades AND live win_rate < backtest − 15pp → **−up to 10 pts** fitness penalty

This is the feedback loop that connects paper trading to the genetic algorithm.

### Arena Champion Boost

After live adjustment:
- Champion strategies (won head-to-head arena) get **+8 pts** fitness
- Their family siblings get **+3 pts** — guides evolution toward parameter families that demonstrated champion-level performance

---

## 8. Evolution Engine

**File:** `backend/strategies/evolution_engine.py`

### Configuration

| Parameter | Value | Notes |
|---|---|---|
| `TOURNAMENT_SIZE` | 7 | Select best from random 7 candidates |
| `MUTATION_RATE` | 65% | 65% of offspring are mutations |
| `CROSSOVER_RATE` | 35% | 35% combine two parents |
| `MIN_PARENT_FITNESS` | 40.0 | Only breed from fit strategies |
| `MIN_PARENT_SHARPE` | 0.20 | Parent must show real edge |
| `BACKTEST_DAYS` | 1825 (5yr, widened from 1095/3yr 2026-07-02 — must match the population re-backtest window or offspring get scored on different data than their parents) | 5-year backtest per offspring |
| `offspring/cycle` | 30 | Raised from 20 post-universe expansion |
| Bootstrap parent tier (2026-07-03) | if even the positive-Sharpe fallback yields 0 parents, breed from the best-fitness strategies that still clear the trade-count floor, regardless of Sharpe sign | Prevents evolution from stalling entirely right after an honest-metrics reset, when the ENTIRE population can legitimately have negative Sharpe — self-limiting, better tiers take over the moment a real positive-Sharpe strategy appears |

### Tournament Selection

Randomly pick 7 strategies from the parent pool; return the one with the highest fitness. This preserves diversity while applying selection pressure.

### Parent Pool Diversity

Parents are capped at **10 per family** to prevent one strong family from monopolising breeding. Pool size capped at 100 to exclude mediocre parents.

### Mutation Operations

| Operation | Description | Meta-Bias |
|---|---|---|
| `threshold_shift` | Nudge a condition threshold ±25% | Gets 2× weight if top-ranked |
| `operator_flip` | Flip `>` to `>=` or vice versa | — |
| `feature_swap` | Replace feature with another from same category | — |
| `rule_add` | Add a new condition from any category | — |
| `rule_remove` | Remove lowest-weight condition (must keep ≥2) | — |
| `regime_expand` | Add one more allowed regime | — |
| `regime_restrict` | Remove one allowed regime (must keep ≥1) | — |
| `param_adjust` | Adjust stop/take-profit/hold ±20% | Gets 2× weight if top-ranked |
| `confidence_adjust` | Nudge min_confidence; 3:1 bias toward lowering | — |

Meta-learner biases the operation pool toward historically successful mutations.

### Crossover

When crossover is selected, the engine takes entry conditions from parent A and risk parameters (SL/TP/hold) from parent B, weighted by their relative fitness.

---

## 9. Meta-Learner

**File:** `backend/strategies/meta_learner.py`

The meta-learner reads 5 signal sources and outputs a `MetaState` dict that the generator and evolution engine use to adapt each cycle.

### Signal Sources

| Source | What it provides |
|---|---|
| `StrategyGraveyard` | Which families die most, in which regimes, with which features |
| `StrategyEvolutionHistory` | Which mutation ops improved fitness (ranked by avg delta) |
| `PaperTrade` outcomes | Which strategy families generated real profit in paper trading |
| `Prediction` outcomes | Model accuracy by regime and confidence band |
| `StrategyV2` top alive | Parameter priors (avg hold, SL, TP) for top-fitness strategies |

### Outputs (MetaState)

| Output | Effect |
|---|---|
| `family_weights` | Generation probability per family (2%–35%); suppresses dying families, boosts live winners |
| `bad_features` | Features in dead strategies but not top ones → generator avoids them |
| `graveyard_zones` | (family, SL) parameter clusters that always die → generator avoids |
| `ranked_mutation_ops` | Mutation engine adds extra slots for top-3 operations |
| `current_conf_floor` | Dynamic minimum confidence: higher when model accuracy is poor in current regime |
| `param_priors` | Avg hold/SL/TP from top alive strategies per family → seeds mutation ranges |

### Family Weight Adjustment Logic

```
death_share > 35% AND avg_dead_fitness < 15  →  weight × 0.25  (suppress hard)
death_share > 25% AND avg_dead_fitness < 25  →  weight × 0.45
death_share > 15%                            →  weight × 0.65
live_win_rate ≥ 60% AND trades ≥ 5          →  weight × 1.50  (strong boost)
live_win_rate ≥ 55% AND trades ≥ 5          →  weight × 1.25
live_win_rate < 40% AND trades ≥ 5          →  weight × 0.40  (suppress)
top_alive avg_fitness ≥ 60 AND count ≥ 5    →  weight × 1.30
```

All weights are renormalised to sum to 1.0.

---

## 10. Daily Research Loop

**File:** `backend/strategies/strategy_research_loop.py`

The research loop runs in the APScheduler strategy step (every 5 minutes during market hours; once at boot).

### Steps

| Step | Action | Notes |
|---|---|---|
| 1 | Generate 50 new candidates | Family-weighted, pre-screened |
| 2 | Backtest up to 300 unscored strategies | Proportional per family, shuffled |
| 3 | Score all strategies with backtest data | Via fitness_engine |
| 4 | Lifecycle sweep | Promote/retire |
| 4B | Live performance adjustment | Fitness ±5-10 from paper trades |
| 4C | Arena champion boost | +8 direct, +3 siblings |
| 5 | Evolve 30 offspring | Tournament → mutate/crossover → backtest → score |
| 6 | Graveyard pattern analysis | Extract failure patterns for meta-learner |
| 7 | Full research reports | Sector, regime, strategy reports |
| 8 | Population snapshot | Counts, avg fitness, distribution |

### Pre-Screen (`_passes_prescreen`)

Before backtesting any candidate:
- Must have ≥2 entry conditions
- All feature names must exist in feature registry
- No features from `meta_state.bad_features`
- DSL structure must be valid (no None thresholds)

Pre-screen failures are immediately retired with reason `prescreen:<reason>` — no backtest wasted.

---

## 11. Self-Learning System

**File:** `backend/learning/learning_loop.py`

The learning system runs daily and makes the ML predictions smarter over time. It is the bridge between trading outcomes and model improvement.

### Step-by-Step

**Step 0: Prediction Outcome Backfill**
- Finds all `Prediction` rows where `actual_return` is NULL
- Computes actual 7-calendar-day return from `DailyPrice` data
- Fills `actual_return` so all downstream steps have real outcomes to analyse
- **Critical**: Without this, steps 2–7 would all return zero results

**Step 1: Pattern Outcome Evaluation**
- Fills `PatternOutcome.actual_return_5d/10d` from price data
- Computes `was_correct` (did direction match?), `outperformed_nifty`
- Feeds the pattern recognition learning pipeline

**Step 2: Failure Analysis**
- `failure_detector.py` identifies mispredictions in recent window
- `failure_classifier.py` categorises each: false_positive, overconfidence, regime_failure, etc.
- `root_cause_engine.py` generates human-readable root cause + recommendation
- Writes `FailureRecord` + linked `LessonLearned` entries

**Step 3: Model Drift Detection**
- Windows: 7d, 30d, 90d (7d added for early warning)
- Computes AUC-ROC vs baseline metric per active model
- Flags drift if current accuracy drops >10% below baseline
- Writes to `ModelDriftHistory`

**Step 3B: Auto-Retrain (NEW)**
- If 30d drift is flagged → calls `check_and_retrain(db, force=False)`
- `check_and_retrain` checks: win_rate < 50% OR model stale > 45 days
- Trains CatBoost + NGBoost + AQRTINet with failure-weighted samples
- New model promoted only if achieves ≥55% win_rate
- Records `LessonLearned` with analysis and recommendations

**Step 4: Confidence Scaling**
- Builds calibration curve (stated confidence vs actual accuracy per bucket)
- Computes ECE (Expected Calibration Error)
- If a model is systematically overconfident at 80%+ (e.g., actual accuracy 60%), scale factor = 0.75
- Scale factors stored as `KnowledgeEvent` metadata; applied by prediction pipeline next day

**Step 5: Feature Decay Detection**
- Computes IC (Information Coefficient = Spearman rank correlation) between feature values and actual returns
- IC over 30d, 90d, 180d windows
- Decay severity: none (|IC|≥0.05), mild (≥0.02), moderate (≥0.01), severe (<0.01)
- Writes `FeatureDecayHistory` — UI can show which features are losing predictive power

**Step 6: Pattern Memory Sync**
- Records `PatternOutcome` rows for recent `Prediction` rows that have `PatternMatch` data
- Links prediction confidence to pattern similarity scores

**Step 7: Daily Knowledge Score (Intelligence Score)**
- 8 components → weighted into 0-100 score:

| Component | Weight | Source |
|---|---|---|
| prediction_quality | 23% | Recent prediction win rate |
| portfolio_quality | 18% | Paper portfolio Sharpe / return |
| risk_quality | 18% | Position sizing, drawdown behaviour |
| learning_quality | 14% | Lessons generated, failures resolved |
| calibration_quality | 9% | ECE — how well-calibrated predictions are |
| feature_quality | 9% | Average IC of active features |
| uncertainty_quality | 5% | Correct uncertainty estimation |
| agent_agreement | 4% | Cross-agent consensus rate |

**Step 8: KnowledgeEvent Log**
- Summary event written to `KnowledgeEvent` table
- Visible in UI learning dashboard

---

## 12. ML Models & Prediction Pipeline

**Files:** `backend/ml/prediction_pipeline.py`, `backend/ml/model_retrainer.py`

### Ensemble Models

Three models trained together; predictions combined via ensemble:

| Model | Type | Strengths |
|---|---|---|
| CatBoostModel | Gradient boosted trees | Handles mixed features; robust to outliers |
| NGBoostModel | Natural Gradient Boosting | Calibrated probability estimates |
| AQRTINet | Custom mixture-of-experts (v4.0) | 4 regime-specialist GBT experts + feature neutralization + conformal intervals |

### Prediction Pipeline (daily)

1. Load latest feature vectors for all 50 symbols
2. For each symbol: run ensemble → get direction probability + return estimate + outperform probability
3. Score confidence (5 components): model_agreement, historical_accuracy, regime_confidence, signal_strength, feature_completeness
4. Apply confidence scaling from calibration audit (Step 4 of learning loop)
5. Run pattern search — record PatternMatch rows
6. Write to `Prediction` table (one row per symbol per day)

### Confidence Components

| Component | What it measures |
|---|---|
| model_agreement | Do all 3 models agree on direction? |
| historical_accuracy | What % of similar past predictions were correct? |
| regime_confidence | Is the current regime one the model performs well in? |
| signal_strength | How far is the feature value from the decision boundary? |
| feature_completeness | What fraction of features have valid (non-null) values? |

### Retraining Triggers

| Trigger | Threshold |
|---|---|
| Recent win_rate | < 50% over last 30 days |
| Model staleness | Not updated in 45+ days |
| 30d drift flag | Drift detection flags >10% accuracy drop |

New model must achieve ≥55% win_rate on test set before being promoted to active.

---

## 13. Key Constants Reference

> ⚠️ **Gate constants live in `backend/strategies/promotion_config.py` — that
> file is the single source of truth; if this doc disagrees, the config
> wins.**

### Fitness Engine (`fitness_engine.py`)

| Constant | Value | Description |
|---|---|---|
| `TARGET_SHARPE` | 1.2 | Full marks at this Sharpe (NIFTY50 benchmark ≈ 0.8) |
| `TARGET_PROFIT_FACTOR` | 2.0 | Full marks at this profit factor |
| `TARGET_WIN_RATE` | 52.0% | Target win rate for full consistency score |
| `TARGET_TRADES` | 100 | Trade count for full longevity score |
| `MIN_TRADES` | 10 | Hard floor below which longevity/cost scores are 0 |
| `ROUND_TRIP_COST_PCT` | 0.28% | Realistic NSE delivery round-trip cost |
| `MIN_EXPECTANCY_NET` | 0.10% | Net per-trade expectancy floor |
| `LIVE_BUFFER_PCT` | 0.05% | Additional live-vs-backtest variance buffer |

### Lifecycle Manager — gates live in `backend/strategies/promotion_config.py` (single source of truth)

| Constant | Value |
|---|---|
| `PROMOTE_THRESHOLD` | 50.0 |
| `RETIRE_THRESHOLD` | 15.0 |
| `MAX_DRAWDOWN_LIMIT` | −35.0% (honest daily MTM drawdown; was an unreachable −100.0 before 2026-07-03) |
| `MIN_BACKTEST_TRADES` | 60 (was 300, found unreachable) |
| `MIN_WIN_RATE` | 52.0% |
| `MIN_SHARPE` | 0.5 (honest daily-series scale; was 0.3 on the old inflated scale) |
| `REQUIRE_OOS_PASS` / `MIN_OOS_SHARPE` | True / 0.2 |
| `BENCHMARK_SHARPE_FACTOR` | 0.8 (× buy-and-hold NIFTY50 Sharpe) |
| `MAX_TRADE_OVERLAP` | 0.60 (Jaccard, duplicate gate) |
| `QUARANTINE_MIN_DAYS` / `_MIN_TRADES` / `_MIN_WIN_RATE` | 60 days / 20 trades / 50.0% (promoted→active gate) |

### Evolution Engine (`evolution_engine.py`)

| Constant | Value |
|---|---|
| `TOURNAMENT_SIZE` | 7 |
| `MUTATION_RATE` | 65% |
| `MIN_PARENT_FITNESS` | 40.0 |
| `MIN_PARENT_SHARPE` | 0.20 |
| `BACKTEST_DAYS` | 1825 (5 years, widened from 1095/3yr on 2026-07-02) |

### ML Retrainer (`model_retrainer.py`)

| Constant | Value |
|---|---|
| `WIN_RATE_FLOOR` | 50.0% |
| `WIN_RATE_TARGET` | 55.0% |
| `ACCURACY_EVAL_DAYS` | 30 |
| `MODEL_STALE_DAYS` | 45 |
| `MAX_RETRAIN_ATTEMPTS` | 5 |

---

## 14. Data Flow & Timing

### Boot Sequence (on backend start)

```
Step 1: New symbol 3-year backfill (30 new stocks) → run_new_symbol_backfill()
Step 1: Normal incremental market data → run_daily_ingestion()
Step 2: Feature engineering → run_incremental_feature_generation()
Step 3: News scrape → run_news_pipeline()
Step 4: Sentiment + regime → run_sentiment_pipeline()
Step 5: ML predictions → run_prediction_pipeline()
Step 6: Paper trading cycle → paper_trade_cycle()
Step 7: Agent research (market, news, pattern, risk) → run_all_agents()
Step 8: Strategy research loop → run_daily_strategy_research()
Step 9: Learning loop → run_daily_learning()
Step 10: Re-backtest stale strategies (Sharpe > 5) + rescore all
```

### APScheduler (recurring)

| Schedule | Task |
|---|---|
| 3:30 PM IST (cron) | Full daily ingestion pipeline (same as boot steps 1-9) |
| Every 1 hour | Agent research cycle |
| Every 5 minutes | Paper trading MTM update |

---

## 15. Known Issues & Design Decisions

### Why MIN_TRADES was 500 (and why it changed)

The original `MIN_TRADES=500` was set assuming daily trading across 100+ stocks. With 3 years of NSE data and 50 stocks, the empirical max observed in backtests was ~430 trades (for the most aggressive momentum strategies). Average was ~52. The 500 threshold was blocking **100% of strategies** from receiving Cost Efficiency or Longevity scores, which made the fitness function effectively just Profitability + Consistency + Robustness (55% of weight). Now set to 10 (hard floor) and 100 (full marks).

### Why total_return is always 0.0 in fitness

`StrategyV2` has no `total_return` column — the backtester doesn't persist cumulative PnL. The Profitability dimension's total_return sub-score therefore always contributes 0. This is acceptable because Sharpe and Profit Factor together capture the same information. Adding a `total_return` column to StrategyV2 and computing it in the backtester would give a 4pp improvement to top strategies.

### Walk-Forward OOS Check

The backtester holds back 20% of the date range as OOS. The OOS slice uses the **same** stock universe — it doesn't simulate live trading (future symbols unknown at entry). This is a limitation: true OOS would need a universe snapshot at backtest_start.

### Why Drift Triggers Retrain Indirectly

Model drift detection (`model_drift.py`) flags drift but does NOT call `check_and_retrain()` directly. The learning loop (`learning_loop.py`) bridges this in Step 3B. The reason for the indirection: drift detection runs per-model/per-window (many iterations), while retraining is a single heavy operation. The step 3B filter (only 30d window flags) prevents over-triggering on short-term noise.

### Self-Learning Doesn't Modify Live Strategies

The learning system updates confidence scaling, model weights (on retrain), and meta-learner state. It does NOT modify DSL conditions of existing live strategies. Mutations come only through the evolution engine. This separation ensures that no automatic code path can change what a promoted strategy does — only evolution can produce a new strategy, which goes through the full backtest → fitness → lifecycle gate again.

---

## Appendix: File Map

```
backend/
├── strategies/
│   ├── strategy_dsl.py          — DSL model (Condition, ConditionGroup, StrategyDSL)
│   ├── strategy_generator.py    — Candidate generation (10 families)
│   ├── strategy_backtester.py   — Signal-driven backtest engine
│   ├── fitness_engine.py        — 6-dimension composite score
│   ├── strategy_lifecycle.py    — State machine (candidate → promoted → retired)
│   ├── evolution_engine.py      — Tournament select → mutate/crossover → evaluate
│   ├── mutation_engine.py       — 9 mutation operations
│   ├── crossover_engine.py      — DSL crossover between two parents
│   ├── meta_learner.py          — 5-source signal aggregation → MetaState
│   ├── strategy_research_loop.py — Daily 8-step orchestration
│   ├── research_engine.py       — Sector/regime/strategy research reports
│   ├── strategy_memory.py       — Population snapshots
│   ├── graveyard_manager.py     — Failure pattern analysis from graveyard
│   ├── live_validator.py        — Live performance validation
│   ├── strategy_store.py        — DB upsert helpers
│   └── strategy_metrics.py      — Metric aggregation helpers
│
├── learning/
│   ├── learning_loop.py         — Daily 8-step learning orchestration
│   ├── model_drift.py           — Rolling accuracy windows, drift flagging
│   ├── root_cause_engine.py     — Failure classification + root cause generation
│   ├── confidence_retrainer.py  — Calibration audit + scaling recommendations
│   ├── feature_decay_detector.py — IC-based feature relevance tracking
│   ├── pattern_outcome_tracker.py — PatternOutcome evaluation
│   ├── pattern_memory.py        — PatternOutcome recording from predictions
│   ├── knowledge_score.py       — 8-component Intelligence Score
│   ├── failure_detector.py      — Identify mispredictions
│   ├── failure_classifier.py    — Categorise failure type
│   ├── knowledge_store.py       — KnowledgeEvent persistence
│   ├── knowledge_graph.py       — Relationship mapping between events
│   ├── lesson_registry.py       — LessonLearned management
│   ├── model_performance.py     — Live accuracy computation
│   ├── weight_optimizer.py      — Ensemble weight optimisation
│   ├── confidence_audit.py      — ECE and calibration curve
│   ├── feature_importance_tracker.py — Feature weight tracking
│   ├── feature_ranker.py        — Feature ranking by IC
│   ├── pattern_evaluator.py     — Pattern match evaluation
│   └── knowledge_metrics.py     — Metric aggregation for knowledge score
│
├── ml/
│   ├── prediction_pipeline.py   — Daily prediction orchestration (all 50 symbols)
│   └── model_retrainer.py       — Accuracy monitoring + triggered retraining
│
└── features/
    ├── feature_generator.py     — Incremental feature computation
    ├── feature_store.py         — Feature vector persistence/retrieval
    ├── feature_registry.py      — Feature name registry
    ├── price_features.py        — Price-derived features
    ├── volume_features.py       — Volume-derived features
    ├── volatility_features.py   — ATR, BB, realized vol
    ├── trend_features.py        — EMA, MACD, ADX, RSI
    └── market_features.py       — Market/sector/breadth features
```

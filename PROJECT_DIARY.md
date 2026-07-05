# AQRTI — Project Diary

*A complete, minute-detail reference to how AQRTI works: what it is, how every subsystem functions, the numbers/thresholds behind each decision, and the full history of how it got here. Written to be printed and read like a book.*

**How to keep this current:** every time meaningful work is done on the project, the newest entry in `CHANGELOG.md` should be reflected here — either as a new line in the Timeline (§9) or, if it changes an actual number/threshold/architecture described elsewhere in this diary, as an edit to that section. See the note at the very end of this file for the exact rule Claude follows.

**Terminology note:** what this diary and the underlying code call "strategies" (the genetic-algorithm-evolved trading rules in `strategies_v2`) are referred to as **algos** in conversation and in newer docs going forward. This file keeps "strategy" in places that quote code/table/column names (e.g. `StrategyV2`, `strategy_lifecycle.py`) for technical accuracy, but "algo" and "strategy" mean the same thing throughout.

**Companion document:** `DATABASE_AND_TRAINING.md` goes much deeper on the database schema and exactly how stored data becomes a trained model or a scored algo — read that alongside §6 and §12 of this file.

Last synced with project state: **2026-07-05** (through CHANGELOG entry `2026-07-05g` — placeholder-data purge, docs fixes, and the Obsidian vault exporter build + scheduler/API wiring — see Timeline phase I below).

---

## Table of Contents

1. [What AQRTI Is](#1-what-aqrti-is)
2. [The Big Picture — How the Pieces Fit Together](#2-the-big-picture)
3. [The 14-Page Dashboard](#3-the-14-page-dashboard)
4. [Data Layer — Where Every Number Comes From](#4-data-layer)
5. [The ML Prediction Engine](#5-the-ml-prediction-engine)
6. [The Strategy Arena — Genetic Algorithm Engine](#6-the-strategy-arena)
7. [Paper Trading Engine](#7-paper-trading-engine)
8. [The Self-Learning System](#8-the-self-learning-system)
9. [Research Agents](#9-research-agents)
10. [Risk Engine & Circuit Breakers](#10-risk-engine--circuit-breakers)
11. [The Daily Pipeline — Minute by Minute](#11-the-daily-pipeline)
12. [Database — All 93 Tables by Subsystem](#12-database)
13. [Backend Module Map](#13-backend-module-map)
14. [Full Project Timeline (Chronological History)](#14-full-project-timeline)
15. [Glossary](#15-glossary)
16. [How This Diary Gets Updated](#16-how-this-diary-gets-updated)

---

## 1. What AQRTI Is

AQRTI (Autonomous Quant Research & Trading Intelligence) is a self-learning research and paper-trading system for the Indian stock market (NSE/BSE), built as a full-stack application: a desktop/browser dashboard on top of a Python backend that runs an autonomous daily pipeline.

**What it is not:** a real-money trading bot. Every trade AQRTI makes is with virtual capital (₹1,00,000 starting balance). It is a *research validation platform* — the entire point is to prove, with honest statistics, whether an automated strategy has a real edge before a human ever risks real money on it.

**Core philosophy carried through the whole codebase:**
- "Survive First. Profit Second." (risk engine's guiding rule)
- "Backtests can lie. Markets do not." (why paper trading exists at all)
- "AQRTI does not predict prices. AQRTI ranks opportunities." (the ML engine outputs ranked confidence, not price targets)
- A strategy that cannot survive forward-testing on data that didn't exist when it was built is not trusted — see §6 and the Trust Overhaul in §14.

---

## 2. The Big Picture

```
Project AQRTI/
├── ui/                     Frontend: vanilla HTML/CSS/JS + Chart.js (no framework)
│   ├── index.html          Structure — all 14 dashboard page sections
│   ├── style.css           Presentation — CSS custom properties, Bloomberg-terminal theme
│   ├── app.js               Logic — navigation, hydration, chart rendering
│   └── api.js               API layer — talks to FastAPI on localhost:8000
│
├── backend/                 Python (FastAPI + SQLAlchemy + SQLite)
│   ├── main.py              Thin entrypoint — imports app, runs uvicorn
│   ├── aqrti/                Core app: API routes, DB models/engine, config, scheduler
│   ├── ml/                   Model training + inference (CatBoost, NGBoost, AQRTINet)
│   ├── strategies/           Genetic-algorithm Strategy Arena
│   ├── paper_trading/        Virtual portfolio simulation + forward-quarantine testing
│   ├── learning/             Self-learning loop: failure analysis, calibration, drift
│   ├── agents/                7 autonomous research agents + CRO daily brief
│   ├── sentiment/             News NLP + sentiment scoring
│   ├── news/                  RSS ingestion + entity/event extraction
│   ├── features/              Feature engineering (148+ features per stock)
│   ├── data_supremacy/        FII/DII flows, options PCR, breadth, sector rotation
│   ├── intelligence/           Phase-9 self-improvement modules (regime discovery, etc.)
│   ├── intelligence_training/  Historical replay + meta-learning training pipeline
│   ├── arena/                  Strategy head-to-head battles, replay animation
│   ├── portfolio/               Portfolio construction, position sizing, rebalancing
│   ├── vault/                   Daily archive/snapshot/backup + date replay
│   └── scripts/                 One-off maintenance/migration scripts
│
├── plans/                   Original design docs (aspirational, Version 1.0 — see §14)
├── docs/                    Ground-truth technical docs (STRATEGY_ARENA.md is canonical)
├── AQRTI_USER_GUIDE.md      Plain-English guide for non-technical reading
├── CHANGELOG.md              Session-by-session change log (the primary source of truth)
└── package.json              npm scripts: dev server + backend launcher
```

### Three-layer UI architecture
```
index.html   → Structure Layer     (semantic HTML, all 14 page sections)
style.css    → Presentation Layer  (CSS tokens — swap entire theme via :root {})
app.js       → Logic Layer
               ├── DataStore        (fallback mock data — mostly removed 2026-06-25)
               ├── ChartRegistry     (owns every Chart.js instance, prevents canvas reuse crashes)
               ├── Page Renderers    (one function per page, independent)
               ├── Hydration Layer   (async live-data fetchers, called every page visit)
               └── Navigation        (re-hydrates on every visit — no stale cache)
api.js       → API Layer            apiFetch / apiPost → http://localhost:8000/api/v1
```

### Tech stack
| Layer | Technology |
|---|---|
| UI | Vanilla HTML5 + CSS3 + ES2022 (no framework) |
| Charts | Chart.js 4.4 |
| Desktop | Electron (`AQRTI Setup.exe`, `AQRTI Portable.exe`) |
| API | Python FastAPI + Uvicorn |
| Database | SQLite via SQLAlchemy ORM, WAL mode |
| ML | CatBoost, NGBoost, AQRTINet (custom) — LightGBM/XGBoost removed 2026-06-27 |
| Data sources | yfinance, feedparser (RSS), NSE bhavcopy CDN, httpx |
| Scheduler | APScheduler — cron + interval jobs |

---

## 3. The 14-Page Dashboard

| # | Page | What it shows | What to actually look at |
|---|---|---|---|
| 1 | **Overview** | Portfolio value (starts ₹1,00,000), daily P&L, market regime, top predictions, equity curve | Check regime + top 5 predictions every morning |
| 2 | **Market Intelligence** | NIFTY 50, BANKNIFTY, VIX, USD/INR, crude, gold, sector strength, breadth, top movers | Breadth >65% + VIX <15 = healthy trading conditions |
| 3 | **Opportunity Rankings** | All predictions ranked by confidence + expected return, risk level, strategy | Focus on confidence >75% + Low/Medium risk |
| 4 | **News Intelligence** | Impact Score (0–100, >75 = critical), sentiment, high-impact feed | Watch for >75 impact events on held positions |
| 5 | **Sentiment Center** | Market score (0–100, <40 fear / >60 greed), company + sector sentiment, velocity | Sentiment >65 + good fundamentals = strong candidate |
| 6 | **Strategy Lab** | Leaderboard by fitness, evolution tree, graveyard, DNA viewer, animated replay | Win rate >50%, Sharpe >1.0 are the health bars |
| 7 | **Model Center** | ML registry, direction accuracy, AUC (0.5=random), walk-forward folds, calibration curve | Accuracy >65% reliable, <60% use caution |
| 8 | **Learning Center** | Knowledge/Intelligence Score (0–100), failure analysis, lessons, feature decay, calibration | 70+ is good; below 60 means predictions are getting less reliable |
| 9 | **Research Ops** | The 7 research agents + CRO, daily brief, pipeline health | The Daily Brief is the single most useful output AQRTI produces |
| 10 | **Paper Trading** | Open positions, equity curve, trade history, analytics | Compare win rate to 50% (random) — 55%+ suggests real edge |
| 11 | **Risk Center** | Exposure %, VaR, drawdown, sector limits, circuit breaker status | Never let max drawdown exceed 15% |
| 12 | **Intelligence Vault** | Date replay (see exactly what AQRTI knew/held on any past day), research archive, backups | Use replay to sanity-check a decision after the fact |
| 13 | **Intelligence Lab** | Regime datasets, meta-learning insights, feature proposals, model/strategy memory | Manual "Run Intelligence Pipeline" trigger lives here |
| 14 | **Data Intelligence** | Data Quality Score, FII/DII activity, options PCR/max pain, earnings calendar, breadth | Quality <70% = treat that day's predictions with more caution |

**Confidence interpretation** (used across every page):
| Confidence | Meaning |
|---|---|
| 90%+ | Very high conviction — rare |
| 75–90% | High confidence — core paper-trading zone |
| 60–75% | Moderate — worth watching, not auto-traded |
| Below 60% | Filtered out by default |

---

## 4. Data Layer

### What AQRTI stores and why (from the original data-architecture principles, still true today)
1. Store everything — storage is cheaper than a future missing signal.
2. Never overwrite raw data — it stays immutable.
3. Every derived feature must be reproducible from raw data.
4. Every prediction must be traceable back to the source data that produced it.
5. Historical data is a competitive asset, not disposable cache.

### Universe coverage — three different numbers, on purpose (verified 2026-07-05)
Different docs have quoted 779 / 641 / 639 / 608 / 352 symbols at different
times — this isn't drift, it's three genuinely different counts that answer
different questions. **Use this convention going forward: always name which
one you mean, don't just say "the universe."**

1. **Total tracked** (`Stock` table row count) — every symbol AQRTI has ever
   registered, active or not. Currently **884**. This is a ceiling, not a
   claim that all of them have usable data.
2. **Active** (`Stock.active == True`) — symbols the system is currently
   trying to keep data flowing for. Currently **393**.
3. **Backtest-eligible** (`get_backtest_universe()` in
   `strategy_backtester.py` — has both price AND feature data, meets the
   liquidity filter) — the ONLY number that matters for "how many symbols
   can an algo actually be tested against right now." Currently **352**
   (verified directly: `DailyPrice` and `FeatureValue` both cover exactly
   352 distinct symbols as of 2026-07-05).

The historical "779 global symbols · 309 Indian (137 NSE + 172 BSE)" figure
below describes the *original* global-expansion target from 2026-06-26 —
kept for historical continuity, but it is the "total tracked" flavor of the
number, not the backtest-eligible one, and the two have diverged since.

- **779 global symbols** (2026-06-26 expansion target) — **309 Indian**: 137 NSE (top NIFTY-50-class names) + 172 BSE (Sensex 30, PSU/private banks, insurance, new-age tech, defence, railways), plus US, UK, EU, Japan, Hong Kong, Korea, Australia, Canada coverage for cross-market features.
- **5 years of price history** per symbol where available: 820,261+ rows as of 2026-06-26 (see §14 phase H for the 2026-07-03 feature-coverage fix that widened this further).
- **Feature store**: 62 engineered features per symbol per day (verified via `feature_registry.py`'s catalog — the number has changed since the original 148-feature design, likely a scope difference between "features described in early design docs" and "features actually implemented," not a regression), 16.7M+ feature rows total as of 2026-07-03 (the single largest table in the database).

### The 7 conceptual data layers
1. **Market data** — OHLCV, adjusted close, VWAP, delivery volume, trade count, market cap, 52-week hi/lo.
2. **Index data** — NIFTY, BANKNIFTY, sector indices (IT, BANK, PHARMA, AUTO, FMCG, METAL, ENERGY, REALTY, MEDIA, PSU, PRIVATE BANK, CONSUMPTION).
3. **Corporate events** — results, dividends, bonuses, splits, management changes, M&A, board meetings, buybacks, promoter activity, block/bulk deals.
4. **News data** — RSS-ingested articles.
5. **Sentiment data** — news/social/analyst/forum sentiment with positive/negative/neutral/confidence/virality/reach/velocity.
6. **Derivatives data** — open interest, OI change, put-call ratio, max pain, build-ups, unwinding, short covering.
7. **Macro data** — repo rate, inflation, GDP, USD/INR, crude, gold, bond yields, VIX, global indices.

### Feature categories (`backend/features/`)
- **Price**: return_1d/5d/21d, momentum_10d/20d, breakout_distance_52w, price_position_52w, relative_strength_nifty_21d, support/resistance distance.
- **Volume**: volume_ratio_20d, delivery_pct, volume_surge_flag, VWAP distance, institutional_flow_proxy.
- **Volatility**: atr_14, bb_width_20, realized_vol_20d, vol_ratio_short_long, hv_percentile_252d.
- **Trend**: ema_20/50, macd_signal, adx_14, rsi_14, stoch_k, price_above_ema50, ema20_above_ema50, ma_20_slope, ma_50_slope, ma_spread, close_ma20_diff, close_ma50_diff.
- **Sentiment**: sentiment_score, sentiment_velocity, news_impact_score, sector_sentiment_score.
- **Pattern**: pattern_confidence, similarity_score.
- **Regime**: regime_confidence, breadth_pct, nifty_trend_score.

### Data integrity safeguards (added during the Trust Overhaul, §14)
- `aqrti/data/integrity_check.py` detects split-adjustment price drift (when an incremental fetch + auto-adjust leaves old rows on the wrong basis) and heals by full re-download + per-symbol feature regeneration. Runs weekly, Saturday 10:00 IST.
- Price sanity validation at ingest: rejects `high < low`, non-positive prices, close outside `[low, high]`; flags moves >25% for review.
- Symbol canonicalization (`ticker_to_symbol`) — `.NS`/`.BO` suffixes collapsed to a single suffix-less symbol, fixing 491 duplicate Stock rows that had accumulated.

---

## 5. The ML Prediction Engine

### Model ensemble (current, as of 2026-07-03 — AQRTINet v3.1)
| Model | Role |
|---|---|
| **CatBoost** | Primary gradient-boosted-tree direction/return model |
| **NGBoost** | Calibrated probability estimates (gives well-formed confidence intervals, not just point predictions) |
| **AQRTINet v3.1** (custom) | In-house model — asymmetric trading loss (false positives penalized 2× harder than false negatives), regime-aware mixture of experts (a separate gradient booster per BULL/BEAR/SIDEWAYS/VOLATILE regime), cross-sectional percentile ranking, 7-fold out-of-fold stacking (uses CatBoost/NGBoost predictions as meta-features), 5-fold Platt-scaled calibration (3-fold below n=500 samples) for well-behaved P(UP) outputs |

### AQRTINet v3.1 — what changed from v3, calibrated for the 5yr/15.8M-row feature store
- **9 domain interaction features** (was 6): kept `ix_momentum_x_trend`, `ix_rsi_x_vol`, `ix_volume_x_momentum`, `ix_breadth_x_beta`, `ix_sector_x_nifty`, `ix_support_x_rsi` from v3; added `ix_rsi_x_momentum` (RSI×5d momentum), `ix_vol_x_breakout` (vol expansion×breakout distance), `ix_trend_x_price` (ADX×price-vs-EMA21) — domain-specific crosses the regime experts can learn from directly rather than re-derive.
- **Temporal decay half-life 252 trading days** (1yr) — recalibrated for the 5yr dataset so recent rows are weighted meaningfully heavier without the decay curve going degenerate over a much longer history than v3 was tuned for.
- **Confident-label weighting**: rows where `|return_5d| < 0.5%` are ambiguous-direction "coin flip zone" labels — down-weighted ×0.3 in training (not dropped, to preserve sample size) so the model isn't misled by noisy direction calls on near-zero moves.
- **Stacking**: 7-fold `StratifiedKFold(shuffle=False)` (was fewer folds in v3) for the out-of-fold CatBoost/NGBoost meta-features.
- **Platt calibration**: 5-fold (3-fold when a regime has <500 training rows) per-regime calibration for P(UP) outputs.

**LightGBM and XGBoost were removed entirely on 2026-06-27** — LightGBM measured 49.04% accuracy (worse than a coin flip) and XGBoost was found to be "actively anti-predictive" at 47.69%. Keeping bad models in an ensemble drags the whole thing down, so they were cut rather than down-weighted.

### Daily prediction pipeline
1. Load feature vectors for all active symbols.
2. Ensemble prediction per symbol → direction probability, expected return estimate, "will it outperform NIFTY" probability.
3. Confidence scoring — 5 weighted components: model agreement, historical accuracy, regime confidence, signal strength, feature completeness.
4. Apply calibration scaling (from the self-learning loop's ECE correction — see §8).
5. Historical pattern search (similarity to past setups).
6. Write a `Prediction` row.

### Retraining triggers
- Recent win rate <50% over a rolling 30-day window.
- Model staleness >45 days since last training.
- A 30-day drift flag from `model_drift.py`.
- A newly trained model is only promoted if it beats ≥55% win rate on its own test set.

### The AUC=1.0 data-leakage bug (important cautionary history — 2026-06-26)
`build_symbol_dataset`'s `pd.merge` created duplicate-suffixed columns (`return_5d_x` / `return_5d_y`). The feature filter only excluded exact `LABEL_COLUMNS` names, so `return_5d_x` — a backward-looking return column correlated almost perfectly with the forward-looking label — leaked straight into training. Every model trained before the fix (v2 through v5) scored a fraudulent AUC of 1.0 / accuracy 0.999 and was invalidated. After the fix, honest AUC settled around 0.50, with the single best feature reaching an information coefficient (IC) of only 0.16 — i.e., genuinely weak-but-real predictive signal, which is what should be expected in liquid equity markets.

### Confidence scale used everywhere
| Score | Category |
|---|---|
| 90–100 | Exceptional |
| 80–89 | Strong |
| 70–79 | Good |
| 60–69 | Weak |
| Below 60 | Ignore |

---

## 6. The Strategy Arena

This is AQRTI's genetic-algorithm strategy discovery engine — the most complex subsystem in the project. It generates trading strategy candidates, tests them against history, scores them, promotes the good ones through a state machine, and evolves the population continuously. `docs/STRATEGY_ARENA.md` is the canonical technical reference; the summary below is drawn from it plus the CHANGELOG history of every threshold change.

### The 7-step closed loop
Generate candidates (10 DSL families) → backtest against 3–5yr / ~50-stock NSE price history → score with a 6-dimension Fitness formula (0–100) → promote/retire via a state machine → evolve via mutation/crossover → learn from failures → adapt weights/floors automatically. **Human approval is required only for the final `active` (real-capital-eligible) status** — everything before that is fully autonomous.

### Strategy DSL (`strategy_dsl.py`)
Each strategy is a JSON document (`strategies_v2.dsl_json`) with: name, family (1 of 10), an entry-condition tree (AND/OR of `Condition(feature, operator, threshold, weight)`), allowed market regimes, `min_confidence` (45–85%), `stop_loss_pct`, `take_profit_pct`, `max_holding_days`. Its `strategy_id` is a SHA-256 hash of the DSL JSON, used for deduplication.

### The 10 strategy families and their default population weights
| Family | Default weight |
|---|---|
| momentum | 18% |
| quality_momentum | 12% |
| breakout | 12% |
| mean_reversion | 10% |
| volume_surge | 10% |
| regime_adaptive | 8% |
| volatility_play | 8% |
| hybrid | 8% |
| institutional_flow | 8% |
| sentiment_driven | 6% |
| *(rl_momentum added 2026-07-01, RL-PPO-adapted)* | — |

Weights aren't fixed — the Meta-Learner (below) adjusts them continuously between 2% and 35% based on which families are actually winning.

50 new candidate strategies are generated per day (reduced from 100/day on 2026-06-28 — quality over quantity).

### Backtester (`strategy_backtester.py`)
- **Transaction cost model**: NSE delivery ≈0.28% round-trip (brokerage 0.03%+0.03%, STT 0.1% sell-only, SEBI/stamp 0.015%+0.015%, slippage 0.05%). Other markets modeled separately (US ≈0.10%, LSE ≈0.77%) but NSE cost is what's used for all live strategy evaluation.
- **Window**: 5 years (1825 days) as of the 2026-07-02 Trust Overhaul (was 1095 days/3yr earlier).
- **Universe**: all active stocks with ≥50 price rows, and — since the 2026-07-02b realism pass — restricted to symbols with average daily turnover ≥ ₹5 crore (illiquid names give fills a real order could never get).
- **Position sizing**: 5% of capital per trade, max 8 concurrent trades (40% max exposure).
- **Signal generation**: load regime → evaluate the entry condition tree → check confidence ≥ `min_confidence` → open or skip. ML predictions are **not** used in backtests (removed 2026-07-02 — using same-day-trained prediction rows on historical dates was look-ahead bias).
- **DSL is fail-closed**: if a (symbol, date) has no feature vector, that entry is blocked entirely — earlier code silently fell back to a generic RSI/EMA rule, corrupting attribution.
- **Intrabar fills**: stop-loss/take-profit checked against the day's open/high/low (not close-only), with gap-through-stop fills and stop-loss priority over take-profit when both trigger in the same bar.
- **Circuit-lock realism**: a bar with high==low is an NSE circuit band (no counterparty) — the position is carried, not filled at a fantasy price.
- **Corrupt-bar guard**: a single trade's return is clamped to `max(2×take-profit, 60%)` — this was added after a real +15,503% trade was traced to one corrupt price bar.
- **Walk-forward OOS check**: 20% out-of-sample holdout; each strategy's 6-month holdout window is shifted 0–59 days by a hash of its own ID (per-strategy OOS window rotation), so the population as a whole can't be overfit by selection even though no individual strategy directly saw a fixed test window.

### Fitness Engine — the scoring formula (`fitness_engine.py`)
```
fitness = 0.28 × Profitability + 0.22 × Consistency + 0.18 × Robustness
        + 0.15 × CostEfficiency + 0.12 × RegimeAdaptability + 0.05 × Longevity
```
- **Profitability (28%)** — Sharpe up to 45 pts (0 at Sharpe=0, full at ≥1.2); Profit Factor up to 35 pts (0 at PF=1.0, full at ≥2.0); Total Return up to 20 pts (full at ≥25%).
- **Consistency (22%)** — Win Rate up to 60 pts (full at ≥52%); Expectancy up to 40 pts (full at ≥2.0%/trade).
- **Robustness (18%)** — Regime breadth up to 40 pts; Max Drawdown up to 40 pts (full at MDD=0, zero at MDD≥20%); overall Sharpe 20 pts; a ×0.5 walk-forward penalty if average holding period <3 days.
- **Cost Efficiency (15%)** — net expectancy = expectancy − 0.05% live-trading buffer; base 70 pts scaling with net expectancy up to 2.0%; frequency bonus up to 30 pts (+30 for hold≥10d, +20 for ≥5d, +10 for ≥3d); hard zero if trade count <10 or net expectancy is negative.
- **Regime Adaptability (12%)** — current-regime Sharpe ÷ 1.2 × 100.
- **Longevity (5%)** — 0 below 10 trades, scaling to full credit at 100+ trades.

### Lifecycle state machine (`strategy_lifecycle.py`)
```
candidate → shadow → promoted → [active]*  (*requires human approval)
                    ↘ retired → graveyard
```
- **Promotion gates (all must pass)**: fitness ≥50.0, trade_count ≥60 (was 300, found unreachable — see §14), win_rate ≥52%, sharpe ≥0.5 (honest scale, raised from 0.3), plus the OOS hard gate, the benchmark gate (Sharpe must reach ≥0.8× buy-and-hold NIFTY50 Sharpe over the same window — "beating do-nothing is mandatory"), and the duplicate gate (reject if backtest trade-overlap with an already-promoted strategy exceeds 60% Jaccard similarity — near-clones are one leveraged bet, not diversification).
- **Retirement**: fitness <15.0, or (for already-promoted strategies) win rate falling below 52%, or **honest max drawdown < −35%** (`MAX_DRAWDOWN_LIMIT` in `promotion_config.py`, added 2026-07-03). This replaced a prior `-100.0` limit that was effectively unreachable — a strategy could score above the retirement fitness floor while carrying a catastrophic drawdown if its rare large losses were outweighed by many small wins, and fitness alone didn't reliably catch that "picking up pennies in front of a steamroller" pattern. The threshold is computed against the honest daily mark-to-market drawdown (post-2026-07 backtester fix), not the old per-trade-chained pseudo-equity number.
- **Quarantine gate on `active`** (added 2026-07-02b — the most important recent change): even after promotion, human approval to `active` status is blocked until the strategy has been promoted for ≥60 days **and** produced ≥20 closed forward-paper (shadow) trades with ≥50% win rate and positive net P&L. This is forward performance on data that did not exist when the strategy was created — the one test that genuinely cannot be overfit. `force=true` can override, but the override is logged.
- Retired strategies are never deleted — they go to `StrategyGraveyard` and feed the Meta-Learner.

### Evolution Engine (`evolution_engine.py`)
- Tournament selection: pick 7 random strategies, breed from the fittest.
- Mutation rate 65% / crossover rate 35%.
- Parent pool requires fitness ≥40, Sharpe ≥0.20; capped at 10 per family, 100 total. If the strict floor yields <20 parents, falls back to the best available positive-Sharpe strategies so evolution never stalls and never breeds from junk.
- 30 offspring per cycle (5-min loop uses a smaller 10-offspring version, gated on backlog size).
- **9 mutation operators**: threshold_shift (±25%, 2× weight if the parent is top-ranked), operator_flip, feature_swap, rule_add, rule_remove (keeps ≥2 conditions), regime_expand, regime_restrict (keeps ≥1 regime), param_adjust (±20%, 2× weight if top-ranked), confidence_adjust (3:1 biased toward lowering confidence, not raising it).
- Crossover takes entry conditions from parent A and risk parameters (stop-loss/take-profit/hold time) from parent B, weighted by each parent's relative fitness.

### Meta-Learner (`meta_learner.py`)
Reads 5 signal sources — the Graveyard, evolution history, real paper-trade outcomes, prediction outcomes, and the current top-alive population — to output family weight adjustments:
```
death_share>35% & avg_dead_fitness<15  → family weight × 0.25
death_share>25% & avg_dead_fitness<25  → family weight × 0.45
death_share>15%                        → family weight × 0.65
live_win_rate≥60% & trades≥5           → family weight × 1.50
live_win_rate≥55% & trades≥5           → family weight × 1.25
live_win_rate<40% & trades≥5           → family weight × 0.40
top_alive avg_fitness≥60 & count≥5     → family weight × 1.30
```
All family weights are renormalized to sum to 1.0 after adjustment. This is how AQRTI "notices" that, say, `breakout` strategies keep dying and quietly stops generating as many of them without any human intervention.

### Daily research loop (`strategy_research_loop.py`) — 8 steps
1. Generate 50 candidates.
2. Backtest up to 300 unscored strategies (proportional/shuffled across families).
3. Score.
4. Lifecycle sweep (promote/retire).
4B. Live performance adjustment (real forward paper results nudge fitness ±5 to −10).
4C. Arena champion boost (winning strategies +8 fitness, family siblings +3).
5. Evolve 30 offspring.
6. Graveyard pattern analysis.
7. Full research reports.
8. Population snapshot.

Also runs a lighter version every 5 minutes via APScheduler (see §11).

### Arena champion grading (`arena_engine.py`) — 2026-07-03 rigor pass
A separate refinement loop distinct from the daily research loop above: it
takes already-`promoted`/`active` strategies and iteratively tries to breed
a "champion" version that fixes a parent's losing days without breaking its
winning ones (Option B regression check — child must retain ≥70% of
parent's winning days and fix ≥50% of parent's losing days).
- **Status isolation**: the arena's own progress tracking
  (`champion`/`refining`/`needs_review`) lives in a dedicated
  `StrategyV2.arena_status` + `arena_rounds` column pair — **never** written
  to the lifecycle's own `status` field. A prior version of the arena wrote
  directly into `status`, which silently collided with the lifecycle state
  machine and let `auto_promote_strategies()` push a strategy straight to
  `active` (bypassing human approval and the paper-trading quarantine
  entirely). Fixed 2026-07-03 — `auto_promote_strategies()` now only
  *logs* eligible strategy_ids, never mutates status.
- **Champion grading now requires** (previously in-sample-only): the
  existing return/drawdown/win-rate gates, a minimum trade-count floor
  (`MIN_CHAMPION_TRADES=30` — a handful of lucky trades can't crown a
  champion), an out-of-sample pass on a held-out 6-month window
  (`OOS_MIN_TRADES=8`, `OOS_MIN_WIN_RATE=48%`, `OOS_MIN_RETURN_PCT≥0`), and
  regime-stratified robustness (rejects any well-sampled market regime
  — `MIN_TRADES_PER_REGIME_TO_JUDGE=5` — with net-negative PnL; a strategy
  that only makes money in one regime isn't robust, it's a lucky fit to
  whichever regime dominated the replay window).

---

## 7. Paper Trading Engine

- **Starting capital**: ₹1,00,000 virtual (configurable ₹10,000–₹10,000,000 in theory).
- **Daily process**: after market close (3:30 PM IST) → generate predictions → pick the best-performing strategy's signals → size positions by confidence → open/close positions automatically.
- **Continuous monitoring** (added 2026-06-27): positions are checked every 5 minutes (not just once daily) against live yfinance prices for stop-loss/take-profit/max-holding-period triggers; new entries open when position slots free up.
- **Promotion-to-real-capital requirements** (design target, gates most of this via the Strategy Arena quarantine described in §6): minimum 60 days paper trading (120 recommended), positive return, acceptable drawdown, positive expectancy, consistent performance.
- **Strategy shadow runner** (`strategy_shadow_runner.py`, added 2026-07-02b): every promoted/active strategy gets its **own** independent virtual book (`strat_<id>`) and is forward-paper-traded daily strictly on its own DSL rules, fail-closed on missing features, with real NSE costs and circuit-band awareness. This is the data source for the quarantine gate in §6 — it is forward performance on data that did not exist at the strategy's creation time, so it can't be gamed by evolution selecting on it.

---

## 8. The Self-Learning System

Daily 8-step (+1) process, `backend/learning/learning_loop.py`:

- **Step 0 — Prediction Outcome Backfill**: computes the actual 7-day forward return from `DailyPrice` for every prediction still missing `actual_return`. Without this step, every step below returns zero — it's the load-bearing first step.
- **Step 1 — Pattern Outcome Evaluation**: fills in realized 5-day/10-day returns for matched historical patterns, flags whether the pattern's prediction was correct and whether it beat NIFTY.
- **Step 2 — Failure Analysis**: `failure_detector.py` finds mispredictions, `failure_classifier.py` sorts them into categories (false_positive, overconfidence, regime_failure, etc.), `root_cause_engine.py` writes a root cause + recommendation as a `FailureRecord` + human-readable `LessonLearned`.
- **Step 3 — Model Drift Detection**: compares 7-day/30-day/90-day rolling accuracy against baseline; flags drift if accuracy drops >10%.
- **Step 3B — Auto-Retrain**: if 30-day drift was flagged, checks win rate <50% or model staleness >45 days, then retrains CatBoost+NGBoost+AQRTINet with failure-weighted samples; only promotes the new model if it hits ≥55% win rate.
- **Step 4 — Confidence Scaling**: builds a calibration curve and computes ECE (Expected Calibration Error); if the model is overconfident at 80%+ stated confidence but only 60% actually correct, applies a 0.75 scale-down factor.
- **Step 5 — Feature Decay Detection**: tracks each feature's information coefficient (Spearman rank correlation) over 30/90/180-day windows; severity graded none (|IC|≥0.05) → mild (≥0.02) → moderate (≥0.01) → severe (<0.01). Severely decayed features get excluded from the next training run.
- **Step 6 — Pattern Memory Sync.**
- **Step 7 — Daily Knowledge Score** (the number shown across the dashboard as "Intelligence Score"), an 8-component weighted composite:

| Component | Weight |
|---|---|
| Prediction quality | 23% |
| Portfolio quality | 18% |
| Risk quality | 18% |
| Learning quality | 14% |
| Calibration quality | 9% |
| Feature quality | 9% |
| Uncertainty quality | 5% |
| Agent agreement | 4% |

- **Step 8 — Knowledge Event log.**

**Important nuance:** the self-learning loop adjusts confidence scaling, model weights, and meta-learner state — but it never directly mutates the DSL rules of an already-live strategy. Only the Evolution Engine produces new strategy variants, and every new variant re-enters the full backtest/fitness/lifecycle gate from scratch. This keeps "learning" from silently rewriting a strategy a human already reviewed.

---

## 9. Research Agents

| Agent | Role |
|---|---|
| Market Research | Macro conditions, breadth, sector rotation, regime |
| Pattern Research | Recurring price patterns across the NSE universe |
| Strategy Research | Discovers/tests new strategies, decay detection, resurrection candidates |
| Model Research | ML performance, drift, feature importance |
| News Research | Reads and scores news for market impact, narrative shifts |
| Risk Research | Portfolio concentration, tail risk, drawdown |
| **CRO** (Chief Research Officer) | Synthesises all 6 agents' findings into the Daily Intelligence Brief |

All 7 run at 100% success rate (after a 2026-06-24 rewrite moved them off querying empty tables onto real `daily_prices`/`index_data`). They run automatically every hour via APScheduler, and can be triggered manually via `POST /api/v1/agents/admin/run-pipeline`.

---

## 10. Risk Engine & Circuit Breakers

- **Position limits**: single position 2–5% initial, 10% maximum; sector exposure maximum 25%; total portfolio exposure maximum 80% (20% cash reserve always held back).
- **Confidence-based position sizing**: 90+ confidence → 5% allocation; 80–89 → 4%; 70–79 → 3%; 60–69 → 1%; below 60 → no trade.
- **Circuit breakers** — trading auto-pauses if:
  | Trigger | Limit |
  |---|---|
  | Daily loss | −3% of portfolio |
  | Weekly loss | −6% of portfolio |
  | Monthly loss | −12% of portfolio |
  
  When triggered, status shows `TRIGGERED` on both the Risk Center and Overview pages.
- **Regime-based posture**: Bull → momentum strategies preferred; Bear → defensive mode; Panic/Volatile → capital preservation mode, reduced position sizes.
- **Risk metrics tracked**: Sharpe, Sortino, Max Drawdown, Expected Shortfall, Value at Risk (VaR), Profit Factor.

---

## 11. The Daily Pipeline

`backend/main.py` is a thin stub — it just imports the FastAPI app and starts uvicorn. The real orchestration is split across two places:

### A. Boot sequence (`aqrti/api/app.py`, runs once when the backend starts)
Each step wrapped in try/except so one failure doesn't take down boot:
1. Market data ingestion
2. Feature engineering (incremental)
3. News collection
4. Sentiment & regime classification
5. Predictions (skipped if today's predictions already exist)
6. Paper trading (skipped if already run today)
7. *(Agent pipeline — skipped on boot, handled by the hourly job instead)*
8. *(Strategy research — skipped on boot, handled by the 5-minute job instead)*
9. Learning loop (light scoring pass, not a full retrain)
10. Fix any inflated-Sharpe strategies left over from the pre-2026-06-26 Sharpe bug

### B. Scheduled jobs (`aqrti/data/scheduler.py`, 675 lines)

**Main daily job** — cron-triggered 15:30 IST on weekdays:
1. Market data (yfinance OHLCV)
2. Global universe seed + incremental download (NSE + BSE + international)
3. Bhavcopy supplement (delivery volume from NSE CDN)
4. Feature generation (incremental)
5. News pipeline
6. Sentiment pipeline (also computes regime)
7. Prediction pipeline (skips gracefully if no active models)
8. Paper trading cycle
9. Strategy shadow paper trading (forward-quarantine evidence, §6/§7)
10. Learning loop (7-day window)
11. Live strategy validation sweep (demotes strategies diverging from their own backtest)
12. Drift-triggered retraining (if 30-day drift flagged within the last 3 days, spawns a background retrain thread)
13. Nine Phase-9 intelligence sub-steps: regime discovery (K-Means) → counterfactual analysis → strategy DNA sync → feature discovery → knowledge graph update → hypothesis engine → champion-challenger model arena → Bayesian uncertainty scoring → multi-agent decision (top 5 symbols)
14. Strategy research loop (generate 50, evolve 20)
15. *(Agent pipeline deliberately not run here — see hourly job below, avoids double-execution)*
16. Vault archive (market snapshot, prediction archive, etc.)
17. Data Supremacy layer (FII/DII, options, breadth, sector rotation, quality scoring)
18. Historical Intelligence Training pipeline

**Other independent jobs:**
| Job | Frequency | What it does |
|---|---|---|
| Hourly agent job | Every 1 hour | Full 7-agent research pipeline + follow-up tasks |
| Strategy loop job | Every 5 minutes | Continuous micro-evolution: generates 20 new candidates only if backlog <200; backtests up to 100 (family-balanced); scores everything with trades; evolves 10 offspring only if backlog <500 |
| Alert check job | Every 5 minutes | Warns if drawdown < −15% or Knowledge Score < 35 |
| Arena job | Every 1 hour (+once on boot) | Auto-promote + self-learning refinement cycle |
| Integrity sweep job | Weekly, Saturday 10:00 IST | Detects/heals split-adjustment price drift |
| Paper trading monitor job | Every 5 minutes (+once on boot) | Checks SL/TP/max-hold on open positions, opens new positions, mark-to-market update |

---

## 12. Database

The SQLite database (`backend/aqrti.db`, several GB, WAL mode) has **93 tables**, grouped by subsystem:

**Core Market Data**: `Stock`, `DailyPrice`, `IndexData`, `CorporateEvent`, `NewsEvent`, `SentimentRecord`, `OptionsData` (legacy)

**Predictions & Trading (legacy)**: `Prediction`, `Trade` (unused, superseded by PaperTrade), `Mistake`, `Strategy` (v1, superseded by StrategyV2), `ModelRecord`

**Portfolio Snapshots & Features**: `PortfolioSnapshot`, `FeatureMetadata`, `FeatureValue` (the largest table — 18.5M+ rows), `EntityMention`, `MarketRegime`

**Model Management**: `ModelVersion`, `ModelMetric`, `WalkForwardFold`, `PatternMatch`, `ConfidenceHistory`

**Paper Trading**: `PaperPortfolio`, `PaperPosition`, `PaperTrade`, `EquityCurvePoint`, `PerformanceSnapshot`

**Learning & Knowledge**: `KnowledgeEvent`, `FailureRecord`, `ModelDriftHistory`, `ModelWeight`, `FeatureImportanceHistory`, `FeatureDecayHistory`, `PatternOutcome`, `KnowledgeScore`, `LessonLearned`

**Strategy Arena**: `StrategyV2` (main population table), `StrategyVersion`, `StrategyPerformance`, `StrategyEvolutionHistory`, `StrategyGraveyard`, `StrategyBacktestTrade`, `StrategyResearchReport`

**Agents**: `Agent`, `AgentTask`, `AgentReport`, `AgentMessage`, `ResearchBrief`, `ResearchFinding`

**Vault / Archive**: `HistoricalReplay`, `RegimeDataset`, `MetaLearningRecord`, `FeatureProposal`, `FeatureValidation`, `ModelMemory`, `StrategyMemory`, `ResearchMemory`, `FailurePattern`, `PredictionPattern`, `MarketSnapshot`, `PredictionArchive`, `PortfolioArchive`, `StrategyArchive`, `KnowledgeArchive`, `ResearchArchive`

**Data Supremacy**: `NSECorporateFiling`, `FIIDIIFlow`, `OptionsChain`, `MarketBreadth`, `SectorRotation`, `EarningsEvent`, `DataSourceHealth`, `DataQualityLog`

**Phase 9 Intelligence**: `DiscoveredRegime`, `DailyRegimeAssignment`, `RegimeTransitionMatrix` (K-Means clustering); `CounterfactualSimulation`, `CounterfactualLesson`; `StrategyDNA`; `FeatureCandidate`; `KnowledgeNode`, `KnowledgeEdge`; `ResearchHypothesis`, `ResearchExperiment`; `ModelArena`, `ArenaEvaluation`; `UncertaintyEstimate`; `SpecialistAgentOpinion`, `ModeratorDecision`; parallel `P9*`-prefixed tables; `ArenaRun`

**Index Futures Segment** (added 2026-07-03, fully parallel to the stock tables above — see `DATABASE_AND_TRAINING.md` §11 for the full schema): `IndexFuturesContract` (lot size/tick size/margin % per index), `IndexFuturesPrice` (continuous monthly-contract OHLC + spot_close + basis, `is_synthetic` flag), `IndexFuturesRoll` (contract-month rollover records), `IndexFuturesFeatureValue` (mirrors `FeatureValue`'s shape, keyed on `index_name` not a `Stock` FK). `StrategyV2` gained two new columns for isolation: `asset_class` (`"stock"` default / `"index_futures"`) and `index_name` — same dedicated-namespace pattern as `arena_status` (§6), so an index-futures strategy can never be mixed into stock arena rounds, stock benchmark comparisons, or stock promotion pools. `IndexFuturesPrice` rows are NOT real traded futures ticks — no free data source carries historical NSE index futures contract prices, so this is a documented cost-of-carry approximation (F = S·e^((r−q)T)) over the real underlying spot index, with `is_synthetic=True` on every row.

---

## 13. Backend Module Map

| Directory | What lives here |
|---|---|
| `agents/` | The 7 research agents + infrastructure (registry, scheduler, messaging, memory, task queue) + specialist agents (alert, data_quality, failure_scientist, feature_discovery, macro_intelligence, model_scientist, sector_intelligence) |
| `aqrti/` | Core app package — `api/` (FastAPI + routes), `config/` (settings), `data/` (scheduler, ingestion, universe, integrity), `database/` (models/engine/session), `utils/` |
| `arena/` | Head-to-head strategy battles — `arena_engine.py`, `replay_engine.py`, `strategy_merger.py` |
| `data_supremacy/` | Alt-data scrapers — bhavcopy, breadth, corporate filings, earnings, FII/DII, options, sector rotation, data quality |
| `features/` | Feature engineering — generator, store, registry, per-category modules |
| `intelligence/` | Phase-9 self-improvement — regime discovery, counterfactuals, strategy DNA, feature discovery, knowledge graph, hypothesis engine, champion/challenger, Bayesian uncertainty, multi-agent decision |
| `intelligence_training/` | Historical replay + meta-training pipeline (the "12-step Intelligence Pipeline" in the UI) |
| `learning/` | Self-learning loop, calibration/ECE, failure detection/classification, feature decay, drift, lessons |
| `ml/` | Training/inference — `model_retrainer.py`, `prediction_pipeline.py`, sub-dirs for confidence/datasets/ensemble/models/patterns/regime/validation |
| `ml_models/` | Serialized trained model files (.pkl) |
| `news/` | News ingestion/NLP — collector, parser, entity extractor, event classifier, impact scoring |
| `paper_trading/` | Virtual portfolio — engine, execution, portfolio, trade, performance tracker, continuous monitor, retrain loop, shadow runner |
| `portfolio/` | Portfolio construction — builder, position sizing, rebalancer, risk allocator |
| `scripts/` | One-off/maintenance scripts (rebacktest, migrations, backfills) |
| `sentiment/` | Sentiment engine — company/market/sector sentiment, regime computation |
| `strategies/` | The Strategy Arena genetic algorithm (§6) |
| `vault/` | Intelligence Vault — archive/backup/snapshot managers, replay engine |

---

## 14. Full Project Timeline

*(Reconstructed from the full CHANGELOG.md. Each phase below corresponds to one or more CHANGELOG entries. When new work happens, add a new phase row — see §16.)*

| Phase | Dates | Theme |
|---|---|---|
| **A. Initial Build** | 2026-06-22 – 06-23 | UI shell (9 pages), backend skeleton, ML ensemble v1 (CatBoost+LightGBM+XGBoost), automated paper trading, Electron desktop app built |
| **B. Live-Data Wiring** | 2026-06-24 | Bloomberg-terminal redesign; killed mock-data hooks across the UI; rewrote all 7 agents to compute real findings; first real strategy backtester (99 trades, 55.6% win rate) |
| **C. Bloomberg v2 & Strategy Tuning** | 2026-06-25 | Deleted the ~340-line mock `DataStore`; full data audit fixing Risk/Feature Intelligence/portfolio bugs; fitness/evolution recalibration; Meta-Learning Engine introduced; Intelligence Score first computed at 71.5; population grew 3,469→4,087, promoted 516→847 |
| **D. Global Universe & Data-Leakage Fix** | 2026-06-26 | Universe expanded 447→608→779 symbols; **critical AUC=1.0 data-leakage bug found and fixed** (see §5); AQRTINet v1 introduced; 9 new Phase-9 intelligence modules added |
| **E. 5-Year Data & RAM Optimization** | 2026-06-27 | 5-year price history downloaded (820k rows); 70% win-rate gate imposed (later loosened); continuous 5-min paper trading monitor added; LITE mode for RAM; LightGBM/XGBoost removed; BSE universe added (309 India total) |
| **F. Self-Learning Loop Closed** | 2026-06-28 | AQRTINet v2 (stacking + Platt calibration); self-learning loop fully wired end-to-end; strategy generation cut 100→30/day for quality; fixed a drawdown-limit bug that was retiring every single strategy |
| **G. Trust Overhaul** | 2026-07-01 – 07-02b | **The most consequential phase.** Discovered Sharpe/Sortino were fabricated system-wide (see below); rebuilt the backtester for honesty; added realism gates and forward-paper quarantine; found only ~12% of strategies have genuine positive Sharpe once measured honestly |
| **H. Feature Coverage Fix, Arena Rigor, Index Futures** | 2026-07-03 | Found and fixed a live bug: feature generation was capped to a trailing 1200-day (3.3yr) window while price history covers 5yr, silently blocking thousands of DSL entries per strategy — widened to 2000 days and re-backfilled (16.7M+ feature rows). Added OOS + regime-robustness gates and `arena_status` isolation to the arena (§6). Added meta-learner shrinkage estimators so small-sample deaths/wins can't swing family weights at full strength. Shipped AQRTINet v3.1 (§5). Cleaned the strategy population (deleted 1,229 zero-trade strategies, reset 926 with real trade history to honestly re-earn scores) — produced the current honest baseline of **927 population / 0 promoted**: no strategy has yet proven a genuine edge under the fully-fixed pipeline, which is the correct and expected state, not a bug. Fixed a real crash (orphaned paper positions from the population cleanup poisoning the DB session on every close — see `strategies/live_validator.py`). Added the evolution bootstrap parent tier (§6) so evolution doesn't stall when literally every strategy in the population has negative Sharpe. Built the Index Futures segment foundation (§12) — separate asset class, isolated from the stock population end-to-end. |
| **I. Docs Audit + Placeholder-Data Purge + Obsidian Exporter** | 2026-07-05 | Full documentation review produced `IMPROVEMENTS.md`, a prioritized backlog (P0 placeholder-data violations, P1 stale/wrong docs, P2 historical-doc labeling, P3 polish). Working that backlog found and fixed three real fabricated-data violations beyond the ones already catalogued: `backend/seed_missing_data.py` (deleted — had written invented earnings actuals and `random.uniform()` options data into the DB as if real), a matching pattern in `fii_dii_scraper.py`'s history-backfill (deleted — wrote randomized FII/DII crore flows indistinguishable from real scraped rows), and a hardcoded fake "Today's Alerts" panel on the Overview page (`index.html`, never wired to JS at all — now hydrated from the real research-findings API). Removed `MOCK_AGENT_DATA`/`MOCK_VAULT_DATA`/dead `USE_MOCK` plumbing from the UI. README/USER_GUIDE corrected to match current code (model stack, family/mutation-op/fitness-dimension counts, algo naming). Also planned and built the Obsidian vault integration (`docs/OBSIDIAN_INTEGRATION_PLAN.md`): OBS-1 built `backend/obsidian/` (`vault_exporter.py`, `renderers.py`, `vault_writer.py`) rendering Daily/Stock/Lesson/Home notes from the DB into a one-way, idempotent, ownership-checked markdown vault — verified against the live DB (1044 notes on first run, 100% unchanged on re-run). OBS-2 then wired it in: Step 13 added to the daily scheduler pipeline (`aqrti/data/scheduler.py`, failure-isolated like every other step) and `POST /admin/obsidian-export?full=true` added to the API, both verified live. Still untouched: Algo/Portfolio notes (OBS-3/4), and the exporter has never been pointed at the real `AQRTI Vault/` OneDrive folder (only scratch paths in testing). |

### The Trust Overhaul in detail (2026-07-01 to 2026-07-02b)

This is worth understanding in full because it's the reason the current system can be trusted at all.

**The problem discovered:** every stored strategy metric in the entire population was inflated. The root cause was that Sharpe and Sortino ratios were computed by taking each trade's *average* per-day return and repeating it across every day of the holding period — which artificially collapses variance and inflates the Sharpe ratio. A spot check on a strategy that had been "promoted" under this math showed its Sharpe swing from **+1.63 to −1.66** once real day-by-day mark-to-market portfolio returns were used instead.

**Other bugs found in the same audit:**
- Stop-loss/take-profit were being checked against the day's *close* only, not intrabar — unrealistic fills.
- The DSL evaluator silently fell back to generic RSI/EMA rules whenever a feature vector was missing, instead of blocking the trade — this let strategies "trade" on rules they never actually had.
- Backtests were using same-day ML predictions on historical dates — look-ahead bias, since those models were trained on the full history including the date being "predicted."
- Indian stocks were being charged US-style transaction costs (0.10%) instead of the correct NSE cost (0.28%) — a symbol-suffix detection bug that affected 1.08 million backtest trades.

**The fix:** a full rebuild of the backtester (`build_daily_portfolio_returns` for honest Sharpe/Sortino), a fail-closed DSL, removal of ML predictions from backtests, correct NSE costs, and a hard out-of-sample gate requiring ≥5 trades / ≥50% win rate / positive expectancy / OOS Sharpe ≥0.2 on a genuinely-unseen 6-month holdout before any strategy could be promoted.

**The follow-up (2026-07-02b):** even the honest backtest wasn't proof enough on its own, because a large-enough evolved population can still overfit *by selection* even if no individual strategy directly saw the test data. So a second layer was added:
- A liquidity filter (≥₹5cr average daily turnover) to stop the backtester from crediting fills no real order could get.
- A benchmark gate — a strategy must beat 0.8× buy-and-hold NIFTY50 Sharpe over the same window. Beating "do nothing" is now mandatory.
- A duplicate gate — reject promotion if a strategy's trades overlap >60% (Jaccard) with an already-promoted strategy, so the promoted set isn't just the same bet cloned many times.
- **Forward-testing quarantine**: every promoted/active strategy now gets forward-paper-traded daily on its own DSL rules in its own virtual book. Approval to `active` (the only status eligible for real capital) is blocked until it has been promoted ≥60 days **and** produced ≥20 closed forward trades with ≥50% win rate and positive net P&L. This is the one test in the whole pipeline that literally cannot be overfit, because the data it's evaluated on didn't exist when the strategy was created.

**The honest result:** of 112 strategies that had previously earned "promoted/active" status under the inflated metrics, the vast majority were demoted back to shadow. Of roughly 700 strategies that had traded at least 60 times, only about **12% showed a genuinely positive honest Sharpe ratio**. That 12% is now the real baseline — evolution breeds against it, not against the old inflated numbers.

---

## 15. Glossary

| Term | Definition |
|---|---|
| **AUC** | Area Under Curve — model accuracy measure (0.5 = random guessing, 1.0 = perfect) |
| **Backtest** | Testing a strategy against historical data |
| **CAGR** | Compound Annual Growth Rate |
| **Circuit Breaker** | Automatic trading pause when losses exceed a threshold |
| **Drawdown** | Drop in portfolio value from its most recent peak |
| **ECE** | Expected Calibration Error — the gap between stated confidence and actual accuracy |
| **Equity Curve** | Chart of portfolio value over time |
| **Expectancy** | Average expected profit/loss per trade |
| **FII/DII** | Foreign / Domestic Institutional Investors |
| **Fitness Score** | AQRTI's own composite 0–100 rating for a strategy (see §6) |
| **Graveyard** | Where retired, failed strategies live — never deleted, used to prevent repeat mistakes |
| **IC (Information Coefficient)** | Spearman rank correlation between a feature and future returns — measures whether a feature actually predicts anything |
| **Jaccard similarity** | Overlap ratio used to detect near-duplicate strategies |
| **Look-ahead bias** | Accidentally letting a backtest use information that wouldn't have been available at the time |
| **Mark to Market** | Valuing an open position at its current price, not its entry price |
| **OOS (Out-of-Sample)** | Testing on data the strategy/model was never trained or tuned on |
| **P&L** | Profit and Loss |
| **PCR** | Put-Call Ratio — >1.2 typically bearish, <0.8 typically bullish |
| **Regime** | Market condition classification: BULL, BEAR, SIDEWAYS, VOLATILE, RECOVERY |
| **Sharpe Ratio** | Return earned per unit of risk taken (>1.0 good, >2.0 excellent) |
| **Sortino Ratio** | Like Sharpe but only penalizes downside volatility |
| **VaR** | Value at Risk — the worst expected daily loss at a given confidence level |
| **Walk-Forward Validation** | Train on the past, test on the future, then slide the window forward and repeat |
| **Win Rate** | Percentage of trades that were profitable |

---

## 16. How This Diary Gets Updated

This file is meant to be a living document — the physical diary should always describe the system as it actually is *today*, not as it was when first written.

**The rule going forward:** whenever a work session produces a new `CHANGELOG.md` entry (a new dated `## [YYYY-MM-DD...]` heading), that entry's substance gets folded into this diary the same session, specifically:

1. **§14 Full Project Timeline** — if the change is a new phase of work (not a small fix), add a new row to the phase table with the date range and a one-line theme, matching the CHANGELOG style already used above.
2. **The relevant numbered section (§4–§13)** — if the change alters an actual number, threshold, model, gate, or architectural piece described elsewhere in this diary (e.g. a new promotion gate, a changed MIN_TRADES value, a new database table, a new agent), that section gets edited in place so the diary never contradicts the running system. Don't just append — update the described state.
3. **The "Last synced" line at the top** — bump to the current date and the latest CHANGELOG entry ID after each update.

Small/cosmetic commits (typo fixes, minor UI tweaks, dependency bumps) do not need a diary update. Use judgment: if a change would make someone re-reading this diary form a wrong mental model of the system, it needs to be reflected here.

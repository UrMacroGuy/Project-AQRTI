# MASTER IMPLEMENTATION ROADMAP

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).

# PROJECT AQRTI

Last Updated: 2026-06-25

---

## PHASE STATUS OVERVIEW

*(Table refreshed 2026-07-05 — see `IMPROVEMENTS.md` P2-3. Everything below Phase 8b predates the 2026-07 Trust Overhaul; treat pre-overhaul "Done" markers as historical record, not a claim that today's numbers match.)*

| Phase | Name | Status | Completed |
|---|---|---|---|
| 0 | Foundation | ✅ Done | Project structure, DB, config, logging |
| 1 | UI Shell | ✅ Done | 14-page terminal, all chart types, navigation |
| 2 | Data Platform | ✅ Done | Market data, feature store (now 5yr history, 16.7M+ feature rows) |
| 3 | ML Prediction Engine | ✅ Done (superseded) | Original ensemble was CatBoost+LightGBM+XGBoost; LightGBM/XGBoost removed 2026-06-27 (sub-coin-flip accuracy) — current stack is CatBoost + NGBoost + AQRTINet v3.1 |
| 4 | News & Sentiment | ✅ Done | RSS ingestion, NLP scoring, sentiment velocity |
| 5 | Strategy Discovery | ✅ Done (superseded) | Original was an 8-family genetic algorithm; now 11 families, 9 mutation ops, 6-dimension fitness — see `docs/STRATEGY_ARENA.md` |
| 6 | Learning System | ✅ Done | Failure analysis, meta-learner (now with shrinkage estimators, 2026-07-03) |
| 7 | Paper Trading | ✅ Done | Auto open/close, full analytics, forward-paper quarantine gate added 2026-07-02b |
| 8 | Research Agents | ✅ Done | 7 agents, daily briefs |
| 8b | Strategy Engine Overhaul | ✅ Done | Fitness recalibration, historical regimes, family-balanced backtest |
| G | **Trust Overhaul** (not in original roadmap) | ✅ Done (2026-07-01–02b) | Discovered and fixed system-wide Sharpe/Sortino fabrication, unrealistic costs, look-ahead bias; added OOS/benchmark/duplicate/quarantine promotion gates. See `PROJECT_DIARY.md` §14 phase G for full detail. |
| H | **Feature Fix, Arena Rigor, Index Futures** (not in original roadmap) | ✅ Done (2026-07-03) | Fixed a live feature-coverage bug, added arena OOS/robustness gates, shipped AQRTINet v3.1, built the Index Futures segment. Current honest baseline: **927 population / 0 promoted** — see `PROJECT_DIARY.md` §14 phase H. |
| 9 | Production Validation | 🔄 In progress | Re-baselined under honest metrics as of the Trust Overhaul — see refreshed criteria below |
| 10 | Real Capital | ⏳ Pending | Requires Phase 9 success metrics under the HONEST gates, not the original pre-overhaul criteria |

---

## PHASE 0 — FOUNDATION ✅
- SQLite database with WAL mode (`backend/aqrti.db`)
- SQLAlchemy ORM models: StrategyV2, DailyPrice, MLPrediction, AgentTask, MarketRegime, etc.
- APScheduler for daily pipeline automation
- Logging system (`aqrti/utils/logger.py`)
- Configuration via pydantic-settings (`aqrti/config/settings.py`)

---

## PHASE 1 — UI SHELL ✅
- 14-page single-page terminal (no framework, vanilla JS + Chart.js)
- Three-layer architecture: HTML structure / CSS tokens / JS logic
- ChartRegistry prevents canvas reuse errors
- DataStore with fallback mock data mirroring API schemas
- Navigation with per-page hydration (re-fetches live data on every visit)
- Pages: Overview, Market, Opportunities, News, Sentiment, Strategy Lab, Model Center, Learning, Research Ops, Paper Trading, Risk, Intelligence Vault, Intelligence Lab, Data Intelligence

---

## PHASE 2 — DATA PLATFORM ✅
- yfinance daily OHLCV ingestion for 20-stock NSE universe
- 148 engineered features per stock (RSI, EMA, ATR, Bollinger, volume ratios, etc.)
- Feature store with incremental updates
- `DailyPrice`, `FeatureRow` models
- Market regime classification: BULL / BEAR / SIDEWAYS / VOLATILE
- **Historical regime backfill:** 227 days computed from price data (2025-06-25 to 2026-06-22)

---

## PHASE 3 — ML PREDICTION ENGINE ✅
- CatBoost + LightGBM + XGBoost ensemble
- Walk-forward cross-validation
- Direction prediction (Bullish / Bearish / Neutral)
- Confidence calibration with ECE tracking
- Intelligence Score: 71.5
- **Known issue:** models output mostly Bearish/Neutral — retrain needed with balanced regime data

---

## PHASE 4 — NEWS & SENTIMENT ✅
- RSS feed ingestion from NSE/BSE/financial news sources
- NLP sentiment scoring per article and company
- Sentiment velocity tracking
- Fear/greed index computation
- Narrative shift detection

---

## PHASE 5 — STRATEGY DISCOVERY ✅

### Generator
- 8 families: momentum, mean_reversion, breakout, sentiment_driven, regime_adaptive, volume_surge, volatility_play, hybrid
- DSL (Domain-Specific Language) defines entry/exit conditions, regime filters, confidence thresholds, SL/TP/holding params
- `min_confidence` range 50–68 (biased low to fire more signals)

### Backtest Engine
- Signal-driven: ML predictions (primary) + RSI+EMA fallback
- 365-day historical window
- Per-day regime lookup from `MarketRegime` table
- Family-balanced batch allocation (proportional slots, all families covered)

### Fitness Engine (5 dimensions)
- Profitability 30%: Sharpe (cap 3.0), profit factor (cap 4.0), total return
- Consistency 25%: win rate vs 55% target, expectancy
- Robustness 20%: regime breadth, drawdown penalty
- Regime Adaptability 15%: performance in current regime
- Longevity 10%: trade count (≥8 required, full credit at 30+)
- Targets calibrated for Indian equity: Sharpe 1.0, PF 1.8, win rate 55%

### Evolution Engine
- Tournament selection (size 5), 200-parent pool with family diversity cap (30/family)
- 65% mutation / 35% crossover
- 11 mutation ops: threshold_shift (2×), operator_flip, feature_swap, rule_add, rule_remove, regime_expand, regime_restrict, param_adjust (2×), confidence_adjust
- Micro-nudge fallback ensures every child has unique DSL hash

### Lifecycle
- `candidate → shadow → promoted → [human] → active`
- Promotion: fitness ≥ 20, trades ≥ 8
- Retirement: fitness < 8
- Graveyard stores lessons from retired strategies

### Population (2026-06-25)
- 4,087 total | 847 promoted | ~3,000 unscored backlog
- Best fitness by family: volatility_play 67.3, momentum 60.6, volume_surge 57.0

---

## PHASE 6 — LEARNING SYSTEM ✅
- Failure analysis: categories, severity, lessons extracted
- Knowledge score tracking (currently 71.5)
- Confidence calibration updates
- Lesson generation on position close

---

## PHASE 7 — PAPER TRADING ✅
- Virtual portfolio: ₹1,00,000 starting capital
- Auto open/close based on top strategy + ML confidence
- Full trade history with entry/exit detail, strategy name, P&L
- Equity curve, performance analytics
- Circuit breakers: −3% daily / −6% weekly / −12% monthly

---

## PHASE 8 — RESEARCH AGENTS ✅

### 7 Agents
| Agent | Role | Avg Duration |
|---|---|---|
| CRO | Aggregates briefs, writes daily intelligence report | ~0.1s |
| Market Research | Macro, breadth, sector rotation, regime | ~0.1s |
| Model Research | Drift, calibration, feature importance | ~0.1s |
| News Research | Breaking news, narrative shifts | ~0.1s |
| Pattern Research | Price patterns, recurring setups | ~0.1s |
| Risk Research | Portfolio concentration, tail risk, drawdown | ~0.1s |
| Strategy Research | Decay detection, resurrection candidates | ~0.2s |

- Daily pipeline: `POST /api/v1/agents/admin/run-pipeline`
- All agents 100% success rate (stale pending tasks cleared)
- `started_at` / `completed_at` timestamps tracked for duration stats

---

## PHASE 8b — STRATEGY ENGINE OVERHAUL ✅ (2026-06-25)

### Problems fixed
- All strategies scoring identically (calibration targets too high for Indian equity)
- Evolution had no parents (MIN_PARENT_FITNESS 40 → 15)
- Volatility_play getting 0 trades (only 1 regime row in DB — all SIDEWAYS)
- Backtest queue starving non-momentum families (no ORDER BY = insertion order)
- Bulk backtest blocking HTTP client for 10+ minutes

### Key changes
- `fitness_engine.py`: TARGET_SHARPE 2.0→1.0, TARGET_WIN_RATE 65%→55%, soft Sharpe floor
- `strategy_research_loop.py`: family-balanced allocation replaces insertion-order query
- `scheduler.py`: stops generating when backlog >200; 100 balanced backtests per 5-min cycle
- `strategies.py` routes: bulk-backtest + full-research-cycle run in FastAPI BackgroundTasks
- `MarketRegime` table: 227 historical days backfilled (BULL 16d, BEAR 62d, SIDEWAYS 127d, VOLATILE 23d)
- `strategy_registry.py`: avg_sharpe excludes retired/archived strategies
- `agent_scheduler.py`: stamps `started_at` on task start for duration tracking
- `task_history.py`: excludes `cancelled` tasks from success rate

---

## PHASE 9 — PRODUCTION VALIDATION 🔄

### Requirements
- [ ] Paper trading > 60 days with positive expectancy
- [ ] Model direction accuracy ≥ 65%
- [ ] Algo win rate ≥ 55% sustained, promoted under the HONEST gates in `promotion_config.py` (fitness/win-rate/Sharpe/OOS/benchmark/duplicate-overlap/drawdown — not the original, since-superseded criteria above)
- [ ] Max drawdown < 10% (retirement gate is now -35% on honest MTM drawdown — see `promotion_config.MAX_DRAWDOWN_LIMIT`)
- [ ] Sharpe ≥ 1.0 on paper portfolio (honest daily mark-to-market scale, not the pre-overhaul inflated per-trade-repeat scale)
- [ ] Options Intelligence data populated
- [ ] All 11 algo families represented in the backtested/scored population

### Known gaps (re-verified 2026-07-05)
- Options Intelligence still shows `no_data` on `GET /api/v1/options-intelligence` — confirmed still true today, real scraper (NSE option-chain API) not consistently returning data outside market hours.
- The "volatility_play at 2% coverage" gap from the original roadmap is **resolved** — verified directly against the DB: volatility_play now has 131 strategies (13% of the 1,059-strategy stock population), on par with other families.
- The "ML model outputs biased Bearish/Neutral" gap is **superseded, not fixed or refuted** — the entire ensemble (CatBoost+LightGBM+XGBoost) that claim was about no longer exists; LightGBM/XGBoost were removed 2026-06-27 and AQRTINet v3.1 was shipped 2026-07-03. Whether the *current* ensemble has a direction bias is an open question that needs its own fresh check, not an inherited answer from the old ensemble.
- **The real current gap, not in the original list**: as of the 2026-07-03 honest re-baseline, the algo population has **0 promoted algos out of 927** — no algo has yet proven a genuine edge under the fully-honest backtester. This is correct, expected behavior post-Trust-Overhaul (see `PROJECT_DIARY.md` §14 phase H), not a bug to fix by loosening gates — but it means Phase 9's "Algo win rate ≥55% sustained" criterion has no candidate to even evaluate yet.

---

## PHASE 10 — REAL CAPITAL ⏳

- Initial capital: ₹5,000
- Requires Phase 9 all green
- Scale only on: positive expectancy, controlled drawdowns, consistent Sharpe > 1.0

---

## AUTONOMOUS DAILY PIPELINE (12 STEPS)

Runs via APScheduler after NSE close (configurable cron):

```
1.  Ingest market data (yfinance OHLCV for 20 stocks)
2.  Feature engineering (incremental update, 148 features)
3.  News ingestion (RSS feeds)
4.  Sentiment scoring (NLP, fear/greed, velocity)
5.  ML predictions (CatBoost + LightGBM + XGBoost ensemble)
6.  Paper trading cycle (open/close positions)
7.  Daily learning loop (failure analysis, lessons, knowledge score)
8.  Strategy research (generate + backtest + score + evolve)
9.  Multi-agent research pipeline (all 7 agents + CRO brief)
10. Intelligence Vault archive (snapshot, predictions, briefs)
11. Data Supremacy layer (FII/DII, options, breadth, sector rotation)
12. Historical Intelligence Training
```

Plus continuous: **Strategy loop every 5 minutes** (100 balanced backtests + evolve 10 offspring when backlog < 500).

---

## YEAR OBJECTIVES

| Year | Goal |
|---|---|
| Year 1 | Profitable research platform (in progress — paper trading live) |
| Year 2 | Self-improving trading intelligence system |
| Year 3 | Institutional-grade autonomous quantitative research platform |

**Final Mission:** AQRTI becomes a continuously learning system that discovers opportunities, validates ideas, manages risk, and compounds knowledge faster than a human trader can.

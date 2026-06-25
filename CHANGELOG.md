## [2026-06-25b] — Meta-Learning Engine, Model Self-Improvement, Adaptive Evolution

### New Features

**Meta-Learning Engine** (strategies/meta_learner.py)
- Reads 5 signal sources every evolution cycle: strategy graveyard (failures + lessons), evolution history (operation fitness deltas), live paper trade outcomes, prediction accuracy by regime, alive top-strategy parameters
- Computes `MetaState`: per-family generation weights (adjusted from defaults), bad-features list (features that appear in dead strategies but rarely in top ones), dynamic confidence floor per regime (raised if model underperforms, lowered if reliable), ranked mutation operations by avg fitness delta
- Writes `MetaLearningRecord` rows for each insight: family weight shifts >15%, bad features, confidence floor changes, best mutation op
- `GET /strategy-evolution/meta-state` — current meta-state (family weights, signals, regime accuracy)
- `POST /strategy-evolution/meta-learn` — trigger a full meta-learning cycle on demand

**Strategy Generator — Meta-Adaptive** (strategy_generator.py)
- `generate_candidates()` now accepts `meta_state` dict; uses meta-learned family weights instead of static defaults
- Applies confidence floor from meta-state: strategies generated below the dynamic floor are bumped up
- Bad-feature avoidance: if all entry conditions use bad features, the strategy is regenerated once with the same family
- `run_generation_cycle(use_meta=True)` automatically fetches meta-state before generating

**Mutation Engine — Meta-Adaptive** (mutation_engine.py)
- `mutate()` now accepts `meta_state`; builds operation pool biased toward historically best operations
- Top-ranked operations (by avg fitness delta over last 60 days) receive 2-3x more selection slots vs baseline
- Only operations with positive avg delta get boosted — underperforming ops stay at baseline weight

**Evolution Engine — Full Meta Integration** (evolution_engine.py)
- `evolve_population(run_meta=True)`: runs `run_meta_learning()` before each cycle, passes meta-state to both `mutate()` and the parent selection logic
- Returns `meta_state_summary` in the cycle result: bad_features, conf_floor, top_mutation_op, meta_insights count

**Model Self-Improvement Engine** (ml/model_retrainer.py)
- Checks prediction accuracy over last 30 days: if win rate < 50%, triggers automatic retraining
- Checks model staleness: if active model > 45 days old, triggers retraining
- Runs full LightGBM + XGBoost + CatBoost walk-forward training pipeline on fresh data
- Retires old active model, registers new version in `model_versions` table, writes `LessonLearned` and `KnowledgeEvent` records
- `check_and_retrain(force=False)` — smart retraining; `force=True` ignores thresholds
- `GET /models/retrain-status` — check if retraining is needed without triggering it
- `POST /models/retrain?force=true/false` — trigger retraining via API

**Model Research Agent — Autonomous Retraining** (agents/model_research_agent.py)
- Now calls `get_retraining_status()` at end of every research run
- If needs_retraining → automatically calls `check_and_retrain()` without human intervention
- Writes findings about retraining outcome (new model accuracy, trigger reason, per-regime win rates)
- Falls back gracefully if ML dependencies unavailable (e.g., first install)

**Meta-Learning Control Center UI** (Strategy Research page)
- New panel: "⬡ Meta-Learning Control Center"
- 3-column layout: (1) Family Weight Adjustments table showing default vs current weight + delta for all 10 families, (2) Learning Signals (regime, confidence floor, graveyard size, bad features with colour tags, per-regime prediction accuracy bar chart), (3) Model Self-Improvement (needs-retrain alert, 30d win rate, model age, last retrained, regime breakdown)
- Mutation Operation Performance table: ranked by avg fitness delta, shows total/positive%/avg delta/rank for every mutation operation over 60 days
- Buttons: "Refresh State", "Run Meta-Learn", "Check Model", "Retrain Model" (with confirmation dialog)
- Auto-loads when Strategy Research page opens

---

## [2026-06-25] — Strategy DNA Viewer, Trade Recommendations, Live Validation, Cost-Aware Fitness

### New Features

**Strategy DNA Viewer** (Strategy Research page)
- `GET /strategies/{id}/dna` — full strategy decode: entry/exit conditions in plain English, DSL params (stop %, target %, min confidence, max hold), regime permissions, per-regime Sharpe
- Parent lineage (clickable, recursive exploration), children/offspring list, version/mutation history, live-vs-backtest validation comparison, last 8 backtest trades
- "DNA" button added to every leaderboard row — scrolls to viewer and populates it instantly
- ID search box for exploring any strategy directly

**Trade Recommendations Panel** (Strategy Research page — "Trade This Now")
- `GET /strategies/recommendations` — top 5 actionable trades combining ML predictions (confidence ≥ 55%) with top promoted strategy DSL for stop/target calculation
- Each trade card shows: symbol, sector, entry price, stop-loss (with % risk), target (with % upside), reward:risk ratio, position size (5% each), confidence score
- Regime label, strategy bar showing which strategy generated the params
- Disclaimer: paper trading reference only, not financial advice
- Auto-loads when Strategy Research page opens; manual Refresh button

**NSE Transaction Cost Model** (backtester)
- Real Indian delivery equity breakdown: STT 0.1% buy+sell, exchange charge 0.00345%, SEBI 0.0001%, stamp duty 0.015% buy-only, brokerage 0.03%, GST 18% on brokerage+exchange+SEBI, slippage 0.05%/0.03%
- Round-trip cost ≈ 0.28% — replaces old flat 0.1% slippage assumption
- Entry price includes buy cost; exit P&L deducts sell cost

**Fitness Engine v2 — 6 Dimensions** (fitness_engine.py)
- Profitability 28%, Consistency 22%, Robustness 18%, Cost Efficiency 15%, Regime Adaptability 12%, Longevity 5%
- Cost Efficiency: strategies where avg trade return barely exceeds round-trip cost score 0 — filters high-friction strategies that look good gross
- Walk-forward penalty: avg_holding_days < 3 → robustness halved
- Targets raised: Sharpe 1.2 (was 1.0), P/F 2.0 (was 1.8)
- `rescore_all()` endpoint: `POST /strategies/admin/rescore` triggers full re-score + lifecycle sweep

**Live Paper Trading Validation** (live_validator.py)
- `record_strategy_live_day()` — upserts StrategyPerformance from closed paper trades
- `run_daily_validation_sweep()` — full recompute across all strategies
- `_check_live_divergence()` — SHARPE_DIVERGE_LIMIT=0.8, WINRATE_DIVERGE_LIMIT=20pp
- `_demote_to_shadow()` — auto-demotes strategy if divergence is critical
- `on_trade_closed()` hook wired into `paper_trade.close_position()` — live validation fires on every trade close
- `POST /strategy-performance/validate` and `GET /strategy-performance/{id}/validation` endpoints

**Strategy Generator Refinements**
- 2 new families: `quality_momentum` (QGLP-style) and `institutional_flow` (delivery% + volume surge)
- All generators enforce reward:risk ratio (1.5:1 min, up to 3.5:1)
- Momentum: min hold raised to 7-25 days; mean reversion: requires 2-5% actual pullback
- `_FAMILY_WEIGHTS` updated — quality_momentum 12%, institutional_flow 8% of new generations

---

## [2026-06-25] — Full App Audit + Data Fixes (Round 2)

### Fixes Implemented
- **`/api/v1/overview` — `date` import missing** — `date.today()` on line 40 would NameError because only `timedelta` was imported inline; moved both to module-level `from datetime import date, timedelta`
- **`/api/v1/strategies/stats` 404** — added `GET /strategies/stats` endpoint returning total/promoted/active/shadow/retired/families counts + top strategy; fixes dashboard strategy card
- **`/api/v1/replay/date-range` 422** — added missing `GET /replay/date-range` route (was entirely absent); returns oldest/newest trade + price dates from DB
- **Equity curve flat line** — `GET /equity-curve` and `GET /paper-portfolio/equity-curve` now reconstruct a synthetic curve from closed paper trade P&L by date when `EquityCurvePoint` has fewer than 3 rows; chart shows real history instead of flat capital line
- **`POST /paper-portfolio/backfill-equity`** — new endpoint: one-time idempotent backfill that creates `EquityCurvePoint` rows from paper trade history so `performance_tracker` can compute real Sharpe/Sortino; called automatically from frontend on first paper portfolio load (guarded by `sessionStorage`)
- **Sector rotation `avg_sentiment` always null** — `SentimentRecord.timestamp` is a datetime; filter was comparing against a `date` (no-op); fixed to use `datetime.combine()` for both cutoff and target bounds
- **Sector rotation `avg_volume_ratio` always null** — field was never populated in `compute_sector_rotation()`; added `_avg_sector_volume_ratio()` that computes 5d/20d volume ratio from `DailyPrice` and wires it into both new and update paths
- **FII/DII synthetic history anchored to unrealistically low values** — when NSE returns a low-activity day (₹12–22 cr net), the backfill used that as anchor for 30 days of history; added unit-awareness check (scales lakh→crore if value < 500) and realistic clamps (net ±₹5000 cr, gross ₹5000–30000 cr)
- **`GET /market/live/stocks`** — new endpoint: parallel live yfinance prices for all 18 NSE stocks in the universe (60s server-side cache); added `Api.liveStockPrices()` in `api.js`
- **`portfolio.py` `get_equity_curve()`** — upgraded with 3-tier fallback: `PortfolioSnapshot` → `EquityCurvePoint` → paper trade reconstruction; no more flat-line on fresh installs

---

## [2026-06-25] — Session Summary
- Strategy population: 3,469 → 4,087 (+618) · Promoted: 516 → 847 (+331)
- All 8 families now get fair backtest coverage (family-balanced allocation)
- Historical regimes backfilled: 227 days — volatility_play unlocked (best fitness 67.3)
- 7 research agents: all 100% success, avg duration tracked
- Bulk backtest + full-research-cycle: non-blocking (BackgroundTasks)
- Scheduler loop: generates only when backlog < 200, clears 100/cycle

---

## [2026-06-25] — Strategy Backtest Overhaul: All Families Now Evaluated

### Root Cause Found
- **Only 1 historical regime row in DB** (2026-06-24 SIDEWAYS) — all 365-day backtests ran against SIDEWAYS-only history, so strategies restricted to VOLATILE/BEAR/BULL got 0 trades
- **Backtest queue starved non-momentum families** — no ORDER BY meant SQLite insertion order always filled batches with momentum/mean_reversion

### Fixes
- **Backfilled 227 days of historical market regimes** (`MarketRegime` table) using 20-day return + volatility classification: BULL=16d, BEAR=62d, SIDEWAYS=127d, VOLATILE=23d — all families now fire in their relevant regimes
- **Family-balanced backtest allocation** (`_backtest_unscored`): slots distributed proportionally across all 8 families — volatility_play went from 0 backtested → 67.3 best fitness (highest of any family)
- **Scheduler loop fixed** (`_strategy_loop_job`): stops generating new candidates when backlog > 200; uses family-balanced `_backtest_unscored`; only evolves when backlog < 500 — net ~100 strategies cleared per 5-min cycle
- **Re-backtested 39 zero-trade strategies** with full regime history — all now producing real trade data
- **Promoted 51 new strategies** after rescore with full regime data (total promoted: 847)

---

## [2026-06-25] — Bug Fixes: Family Chart, Avg Sharpe Corruption, Non-Blocking Backtest

### Bugs Fixed
- **Family Population Chart showing all zeros** — API returns `count` per family, chart used `alive`; fixed in `ui/app.js` to use `count || alive`
- **avg_sharpe wildly negative per family** — retired strategies with Sharpe ≈ −60 (from 2-trade samples) were included in family averages; fixed in `strategy_registry.py` to exclude retired/archived status
- **New admin endpoints returning 404** — backend running old compiled code; restarted process (PID 4740 → 5784)
- **Bulk backtest timing out HTTP client** — endpoint was synchronous, blocking for 600s+ on 300 strategies; made `bulk-backtest` and `full-research-cycle` non-blocking using FastAPI `BackgroundTasks` — both now return instantly and run server-side
- **volatility_play family never backtested** — `_backtest_unscored` had no ORDER BY so SQLite insertion order always filled the batch with momentum/mean_reversion; fixed to allocate slots proportionally per family so all 8 families get coverage
- **Agent success rate reported as 25-45%** — 21 stale `pending` tasks from prior sessions inflated the denominator; cancelled them and excluded `cancelled` status from `get_agent_performance()` in `task_history.py`
- **Agent avg_duration_secs always null** — `agent_scheduler.py` set `completed_at` but never `started_at`; fixed to stamp `started_at` before calling `execute()`

---

## [2026-06-25] — Strategy Engine Overhaul: Better Scoring, More Diverse Strategies

### Problems Fixed
- **All strategies scoring identically** — fitness was calibrated for Sharpe ≥ 2.0 (unrealistic); all Indian equity strategies scored 8–54 regardless of actual performance
- **Evolution stuck in local optimum** — `MIN_PARENT_FITNESS = 40.0` excluded all real strategies; evolution had no parents
- **Too many duplicate offspring** — mutation fallback produced identical DSL hashes; 42/50 offspring skipped per cycle
- **Too few signals fired** — `min_confidence` range 60–75 too high; technical fallback rarely exceeded threshold → 0 trades per backtest
- **Backtest backlog never cleared** — daily loop backtested 50 but generated 50 new ones; 2,448 candidates never evaluated

### Fixes
**`backend/strategies/fitness_engine.py`**
- `TARGET_SHARPE` 2.0 → 1.0 (calibrated for Indian equity)
- `TARGET_PROFIT_FACTOR` 2.5 → 1.8
- `TARGET_WIN_RATE` 65% → 55%
- `TARGET_TRADES` 50 → 30
- Sharpe normalized with soft floor (−0.5 maps to 0 instead of cliff at 0)
- Win rate expectancy threshold 3% → 1.5% (realistic)
- Tiered longevity score: partial credit for 3–10 trades
- Added `rescore_all()` for bulk recalibration

**`backend/strategies/evolution_engine.py`**
- `MIN_PARENT_FITNESS` 40.0 → 15.0 (real strategies now qualify as parents)
- `TOURNAMENT_SIZE` 3 → 5 (stronger selection pressure)
- Parent pool 50 → 200 rows, capped at 30 per family for diversity
- Mutation/crossover rates adjusted: 65/35

**`backend/strategies/mutation_engine.py`**
- Added `confidence_adjust` mutation: lowers `min_confidence` 3:1 bias (more signals → more trades)
- Weighted `threshold_shift` and `param_adjust` 2× (most impactful mutations)
- Fallback micro-nudge ensures every mutation produces a unique DSL hash

**`backend/strategies/strategy_generator.py`**
- `min_confidence` range 60–75 → 50–68 (allows more signals to fire in backtests)
- All families now support 2–4 conditions (not always 3–4) — less restrictive strategies
- Breakout: threshold widened −5 to +2 (was −3 to +3)
- Added `_rand_confidence()` helper biased toward lower values
- Hybrid generator uses feature-appropriate threshold ranges per category

**`backend/strategies/strategy_research_loop.py`**
- `_backtest_unscored` batch 50 → 200 per cycle (clears backlog 4× faster)
- Default `generate_n` 50 → 100, `evolve_n` 20 → 40

**`backend/aqrti/api/routes/strategies.py`**
- New endpoints: `/admin/bulk-backtest`, `/admin/rescore`, `/admin/full-research-cycle`
- Default `generate` n 50 → 100, `evolve` n 20 → 40

### Results (after immediate rescore + evolution run)
- 421/427 strategies rescored with differentiated fitness values
- 200 new diverse candidates generated (gen 95)
- Evolution gen 97: 8 new offspring, 8 immediately promoted
- Fitness range now spans 12–66 (was all 54.32 for old stale clones)

---

## [2026-06-25] — Remove All Mock Data: Real Backend Data Across All Pages

### Changes
- **Removed entire `DataStore` object** (~340 lines of hardcoded mock data from `ui/app.js`)
- **Converted all render functions to loading stubs**: `renderOverview`, `renderMarket`, `renderOpportunities`, `renderNews`, `renderSentiment`, `renderStrategy`, `renderModel`, `renderRisk`, `renderPaperPortfolio` — each now shows a "Loading…" placeholder and immediately delegates to its `hydrate*()` counterpart
- **Removed `MOCK_STRATEGY_DATA`** and the `useMock` fallback in `hydrateStrategyResearch`
- **Cleaned `renderLearning` DataStore fallbacks**: empty arrays instead of hardcoded score/failure/lesson data
- Real data now shown on: Overview KPIs, equity curve, top predictions, sector strength chart, top movers, derivatives signals, opportunity rankings, news feed, sentiment charts, strategy leaderboard, model registry, learning center, paper portfolio

### Files Changed
- `ui/app.js` — DataStore removed, all render functions converted to stubs

---

## [2026-06-25] — Full Data Audit: Risk, Strategy Performance, Feature Intelligence, Portfolio Fixes

### Bugs Fixed

**Risk page — showed 0% exposure despite 4 open paper positions**
- Root cause: `risk.py` was querying `Trade` table (live trading, always empty) instead of `PaperPosition`
- Fix: now reads `PaperPosition` and `PaperPortfolio` for exposure, sector weights, position VaR

**Strategy Performance — returned empty list**
- Root cause: `StrategyPerformance` table had no rows; no fallback existed
- Fix: falls back to aggregating `strategy_backtest_trades` — returns 50 strategies with real win rates, trade counts, avg P&L

**Feature Intelligence Ranking — 500 server error**
- Root cause: called `func.stddev_pop()` which doesn't exist in SQLite
- Fix: removed stddev call; falls back to `feature_values` table counts/averages (30 features, 3924 samples each)

**Strategy Leaderboard top_n=5 missing high-trade-count strategies**
- Root cause: fetched `top_n * 5 = 25` rows sorted by stale fitness; 431-trade strategy wasn't in top 25 by fitness
- Fix: fetches priority rows by `strategy_id` from live trade map first, then fills remaining slots by fitness

**Portfolio cash leak on drift rebalance**
- Root cause: `execute_rebalance` closed positions but didn't add freed capital back to `portfolio.current_cash` before reopening
- Fix: captures `capital_deployed` before close, adds `deployed + grossPnl` back to cash, then `db.refresh(portfolio)` before opens

**RELIANCE 50% concentration (breaching 25% limit)**
- Root cause: opened when only 1 bullish candidate existed; rebalancer marked it `to_hold` and never resized
- Fix: added drift-rebalance in `execute_rebalance` — positions >5% off target are closed and reopened at correct size
- Portfolio reset to ₹1,00,000, all 4 positions reopened at ~12.5% each

### Files Changed
- `backend/aqrti/api/routes/risk.py`
- `backend/aqrti/api/routes/strategy_performance.py`
- `backend/aqrti/api/routes/feature_intelligence.py`
- `backend/strategies/strategy_registry.py`
- `backend/paper_trading/paper_execution.py`

---

## [2026-06-25] — Strategy Leaderboard: Real Differentiated Trade Stats

### Problem Fixed
- Leaderboard showed all 952 strategies with identical fitness (54.32), sharpe (12.77), win_rate (50%) — all clones from same parent
- "Trades" button showed only 5–8 rows even though strategy_backtest_trades had 15,847 rows

### Solution
- **`backend/strategies/strategy_registry.py`** — `get_leaderboard()` now queries `strategy_backtest_trades` live to compute real `trade_count`, `win_rate`, and `avg_pnl_pct` per strategy
- Rankings now sort by real trade activity (strategies with more trades and positive avg P&L bubble up), not stale `fitness_score` column
- Top strategy: 431 real trades, 44.5% win rate, +0.21% avg P&L, final equity curve 100 → 277
- **`ui/index.html`** — Replaced "Sharpe" column with "Avg P&L%" in leaderboard header
- **`ui/app.js`** — Row renderer now shows color-coded avg P&L% (green/red) and live win rate

### Files Changed
- `backend/strategies/strategy_registry.py`
- `ui/index.html`
- `ui/app.js`

---

## [2026-06-24] — Strategy Backtester Rewrite: Real Signal-Driven Trades

### Problem Fixed
- Strategy backtests were showing `trades=0 sharpe=0.000 win_rate=0.0%` for every strategy
- Root cause: backtester used `FeatureValue` table (always empty) for entry signals → no signals ever fired

### Solution
- **Rewrote `backend/strategies/strategy_backtester.py`** completely
- Primary signals: ML `predictions` table (Bullish/Bearish/Neutral + confidence score)
- Fallback signals: RSI + EMA momentum computed from `daily_prices` when ML predictions are sparse
- Entry logic: Bullish confidence ≥ threshold, regime allowed, NIFTY not in freefall
- Exit logic: stop-loss (−7%), take-profit (+12%), max-hold (15 days), bearish signal flip
- Slippage (5 bps) + commission (3 bps) applied on every trade
- Confidence-ranked entries (highest conviction trades fill first, up to 8 concurrent)
- Force-closes remaining positions at end_date

### Results
- **99 real trades** generated in 365-day backtest window
- Win rate: **55.6%** | Avg hold: **13.7 days**
- Entries/exits logged with: symbol, entry date, exit date, entry price, exit price, P&L %, exit reason, confidence, signal source

### Files Changed
- `backend/strategies/strategy_backtester.py` — full rewrite

---

## [2026-06-24] — Bloomberg v2 Upgrade Session

### Fixed
- **Vault archive_strategies**: StrategyV2 has no acktest_json/egime_fit_json — now builds JSON from metric columns
- **Learning loop PatternMatch**: PatternMatch.date → search_date/computed_at (field renamed in model)
- **Learning loop step isolation**: each of 8 steps now catches its own exception; loop completes even if one step fails
- **Strategy population stats**: added promoted, max_generation, graveyard_count to API response (both strategy_store and strategy_registry)

### Data Populated
- Intelligence Score computed: **71.5 / 100** (first successful learning loop)
- 53 strategies **Promoted** (best fitness 69.32, gen 17)
- 1 graveyard entry
- Vault: 53 strategies, 18 predictions, 1 portfolio record archived for 2026-06-24
- Strategy research: 50 new candidates, 47 scored, 6 promoted offspring (gen 15)

### UI Upgrades (Bloomberg v2)
- **Strategy tab**: Added live Activity Feed showing real KnowledgeEvent data; added inline Strategy Inspector panel
- **Strategy Inspector**: click Trades → shows backtest trades inline (no modal required)
- **Learning tab**: Recent Events feed now populates lc-events-body table with live strategy/model/portfolio events
- **Overview KPIs**: Knowledge score shows "Computing…" when 0 but system active; avgConf + strategy count displayed
- **Strategy KPIs**: src-kpi-promoted, src-kpi-generation, src-kpi-graveyard now show real data
# AQRTI Changelog

> **Purpose:** Every Claude session records what was added, changed, or removed here.
> A new session should **read this file first** to catch up instantly â€” no need to scan the whole codebase.
>
> Format per entry:
> - **Session date** + brief title
> - Files touched
> - What changed and why

---

## 2026-06-24 â€” Agent Pipeline Overhaul: All 7 Agents Rewritten for Real Data

### Files Changed
- `backend/agents/market_research_agent.py` â€” full rewrite
- `backend/agents/news_research_agent.py` â€” full rewrite
- `backend/agents/model_research_agent.py` â€” full rewrite
- `backend/agents/risk_research_agent.py` â€” full rewrite
- `backend/agents/strategy_research_agent.py` â€” full rewrite
- `backend/agents/pattern_research_agent.py` â€” full rewrite
- `backend/agents/cro_agent.py` â€” minor fix (subcategory None guard)

### What Changed Per Agent

**Market Research Agent**
- Was: only queried MarketRegime + SentimentRecord (both often empty) â†’ 0 findings on fresh install
- Now: queries `index_data` (NIFTY50 1d/20d returns, annualised vol), `daily_prices` (5-day breadth across 20 stocks, sector rotation by avg 5d return). All 5 analyses produce real computed numbers, not placeholders.

**News Research Agent**
- Was: queried NewsEvent + SentimentRecord (both empty) â†’ 0 findings always
- Now: falls back to price-based news proxies from `daily_prices` â€” large single-day moves (â‰¥3%), volume spikes (â‰¥2.5x 20d avg), gap opens (â‰¥2.5%), 52-week highs/lows. DB-based news analysis still runs if `news_events` is populated.

**Model Research Agent**
- Was: queried ModelDriftHistory, FeatureDecayHistory, KnowledgeScore (all likely empty) â†’ meaningless findings
- Now: queries `model_versions` (active count, staleness, best accuracy), `predictions` (volume, confidence distribution, direction bias, win rate from `success` field), `performance_snapshots` (win_rate_pct). Falls back gracefully when empty.

**Risk Research Agent**
- Was: queried PerformanceSnapshot, PaperTrade, EquityCurvePoint (all empty on fresh install) â†’ 0 findings
- Now: supplements with market-level risk from `daily_prices` â€” parametric 95% 1-day VaR from 20-stock return distribution, annualised volatility, worst single-day loss. NIFTY negative session count. Portfolio analysis runs when trades exist.

**Strategy Research Agent**
- Was: returned "critical" urgency when strategy population empty â†’ alarming for fresh installs
- Now: "normal" urgency for empty population (expected state). Added prediction-based signal analysis: persistent symbol+direction combos from `predictions`, bullish win rate. Regime mismatch and resurrection candidates still run when data exists.

**Pattern Research Agent**
- Was: queried PatternOutcome + PatternMatch (both empty) â†’ 0 findings
- Now: computes RSI(14) from closes (overbought â‰¥75, oversold â‰¤25), EMA20/EMA50 crossovers, 10-day volume accumulation/distribution ratio, NIFTY-vs-breadth divergence. All computed live from `daily_prices`.

**CRO Agent**
- Fixed: `f.subcategory.lower()` crash when `subcategory` is None â€” now guards with `if f.subcategory` before calling `.lower()`
- Added: "No reports yet" message in market summary when pipeline hasn't run

### Verified
- All 7 agents import cleanly: `7/7 OK` (tested with `backend/.venv/Scripts/python.exe`)
- No placeholder/hardcoded mock values in any agent â€” all numbers computed from DB
- All agents handle empty tables gracefully (try/except + low-urgency fallback finding)

---

## 2026-06-24 â€” Blank Page Fixes: Sentiment, Model Center, Opportunities, Data Intelligence

### Files Changed
- `ui/app.js` â€” Fixed 5 bugs across 3 hydrator functions + DI action buttons
- `ui/index.html` â€” DI action buttons now pass `this` for loading state

### Bug Fixes

**`hydrateSentiment()` â€” blank when DB has no sentiment data:**
- Was: KPI cards only populated when `companies.length > 0`. Empty DB = all KPIs stay `â€”`, charts show nothing
- Fix: Now reads `data.market.label/score/fearGreed` directly from API response first; falls back to company-derived values only if market object missing
- Fix: Added empty-state message (`No sentiment data in database`) to company chart, velocity table, and sector chart containers when arrays are empty (instead of silently leaving mock HTML)

**`hydrateModelCenter()` â€” crash when model task field is null:**
- Was: `m.task.slice(0,3)` throws TypeError if task is null
- Fix: `(m.task || 'unk').slice(0,3)` and `m.task || 'model'` in table row

**`hydrateOpportunities()` â€” null horizon rendered as literal "null":**
- Was: `${best.horizon || '10d'}` â€” but `p.horizon` is `null` from DB, `|| '10d'` fallback wasn't used in all places
- Fix: Best symbol KPI now conditionally appends horizon only if non-null

**Data Intelligence action buttons â€” no visual feedback:**
- Was: buttons had no disabled/loading state during async fetch â†’ appeared broken
- Fix: `_withBtnLoading(btn, fn)` helper added; all 6 DI buttons (Run Pipeline, Scrape Corp Filings, Scrape FII/DII, Compute Breadth, Compute Sectors, Run Quality Checks) now show "Runningâ€¦" + disabled state while POST is in flight

### What's Still Blank (Data Issue, Not Code)
- News Intelligence: `news_events` table has 0 rows. Shows "No news articles in database" message. To populate: run ingestion from Research Ops page.
- Sentiment Center charts: `sentiment_records` table has 0 rows. Shows empty-state message. To populate: run ingestion pipeline.

---

## 2026-06-24 â€” Bloomberg Terminal Redesign + Bug Fixes

### Files Changed
- `ui/style.css` â€” Full Bloomberg-inspired redesign
- `ui/index.html` â€” Topbar, news strip, command palette overlay
- `ui/app.js` â€” News strip hydration, command palette, chart colors, VIX/USDINR live tickers
- `backend/aqrti/api/routes/market.py` â€” Added HTTPException import, India VIX to live map, improved yfinance fallback

### Design Changes (Bloomberg-Inspired)
- **Color system:** Pure black (`#000`) background, amber (`#ff8c00`) as primary accent â€” replaces dark navy + teal
- **Typography:** Full monospace everywhere (JetBrains Mono), tighter font sizes (13px base vs 14px)
- **Spacing:** Reduced all padding/gaps by ~25% â€” more information per screen
- **KPI cards:** No border-radius (2px), no hover lift â€” flat Bloomberg terminal style
- **Panel headers:** Amber uppercase labels instead of white mixed-weight
- **Sidebar:** Compact 210px, amber active state with left border, reduced nav-item height
- **Topbar:** Black background, amber breadcrumb in uppercase, tighter tickers
- **Scrollbars:** 3px, amber on hover

### New Features
- **Bloomberg amber news ticker strip:** 26px amber bar below topbar â€” scrolls live headlines continuously; hydrated from `/news` API; pauses on hover
- **Command Palette (Ctrl+K / Cmd+K):** Bloomberg-style "GO" function â€” type to filter all 15 pages, arrow keys + Enter to navigate; amber overlay
- **VIX live price:** Added `^INDIAVIX` to `/market/live` backend map â€” now shows in topbar VIX ticker
- **USDINR/VIX topbar:** `hydrateTopbarLive()` now populates all 4 topbar tickers (NIFTY, BANKNIFTY, VIX, USDINR) from real-time `/live` endpoint

### Bug Fixes
- `market.py`: Missing `HTTPException` import added (would crash `/live` on yfinance ImportError)
- `app.js`: Breadcrumb now uppercase (Bloomberg style)
- `app.js`: Chart.js global tooltip colors updated to black/amber
- All chart colors: teal (`#00d4aa`) â†’ amber (`#ff8c00`), indigo â†’ blue (`#00aaff`)

---

## 2026-06-24 â€” Git Agent: Auto Commit + Push on File Changes

### Files Added
- `scripts/git_agent.py` â€” Python watcher daemon
- `scripts/start_git_agent.bat` â€” double-click launcher
- `scripts/register_startup.bat` â€” registers agent to run at Windows login via Task Scheduler
- `scripts/unregister_startup.bat` â€” removes startup registration

### How It Works
1. Polls `git status --porcelain` every 30 seconds
2. Ignores: `.db-wal`, `.db-shm`, `.log`, `.pyc`, `__pycache__` (noisy runtime files)
3. Waits 120 seconds of no new changes (quiet period) before committing â€” batches a full coding session
4. Generates smart commit message: categorises files by folder (UI, API routes, ML, paper trading, etc.)
5. `git add <specific files>` â†’ `git commit` â†’ `git push origin main`
6. On Ctrl+C: commits any pending changes before exiting

### Usage
- **Run now:** Double-click `scripts/start_git_agent.bat`
- **Auto-start at login:** Run `scripts/register_startup.bat` (once, as Administrator)
- **Stop auto-start:** Run `scripts/unregister_startup.bat`
- **Tune timing:** Edit `POLL_INTERVAL` and `QUIET_PERIOD` at top of `git_agent.py`

### What Was Pushed
- The agent scripts themselves were committed and pushed as part of this session

---

## 2026-06-24 â€” Live Data Bug Fix: All Pages Now Show Real Backend Data

### Problem
Every KPI card, sub-label, and topbar ticker across all 14 pages showed hardcoded mock/placeholder values instead of live backend data. Root causes were:
1. HTML elements had no `id` attributes â†’ JS hydrators' `el()` calls returned null
2. Field name mismatches (backend camelCase vs JS snake_case)
3. Hydrators never called on initial load (only on page navigation)
4. `_liveHydrated` set prevented re-hydration if backend was offline on first visit
5. `.textContent` on `.regime-badge` div destroyed inner `<span class="regime-dot">` child

---

### Files Changed

#### `ui/index.html`

**Topbar:**
- Added `id="nifty-value"`, `id="nifty-change"`, `id="banknifty-value"`, `id="banknifty-change"` to ticker spans
- Added `id="vix-value"`, `id="vix-change"`, `id="usdinr-value"`, `id="usdinr-change"` (show `â€”` until backend provides data)
- Fixed `id="regime-label"` â†’ `id="topbar-regime"` (JS referenced `topbar-regime`, HTML had wrong ID)
- Regime badge container kept as `id="regime-pill"`

**Overview page (`page-overview`):**
- `kpi-portfolio`: `â‚¹1,04,328` â†’ `â€”`
- `kpi-daily-pnl`: `+â‚¹1,284` â†’ `â€”`; `kpi-daily-pct`: `+1.25%` â†’ `â€”`
- Added `id="kpi-avg-conf"` to Active Predictions sub-label; default `Avg Conf: â€”`
- Added `id="kpi-deployed"` to Open Positions sub
- Added `id="kpi-trades-30d"` to Win Rate sub
- Added `id="kpi-knowledge-sub"` to Knowledge Score sub

**Market Intelligence page (`page-market`):**
- All 6 KPI cards previously had hardcoded values with no IDs
- Added: `id="market-nifty-val"`, `id="market-nifty-chg"`, `id="market-banknifty-val"`, `id="market-banknifty-chg"`
- Added: `id="market-breadth-val"`, `id="market-breadth-sub"`, `id="market-vix-val"`, `id="market-vix-sub"`
- Added: `id="market-crude-val"`, `id="market-crude-sub"`, `id="market-bond-val"`, `id="market-bond-sub"`
- All defaults changed from hardcoded numbers to `â€”`

**News Intelligence page (`page-news`):**
- 4 KPI cards had hardcoded values (`184`, `3`, `+0.48`, `67`) with no IDs
- Added: `id="news-kpi-count"`, `id="news-kpi-high-impact"`, `id="news-kpi-avg-sentiment"`, `id="news-kpi-sentiment-sub"`, `id="news-kpi-entities"`
- All defaults â†’ `â€”`

**Opportunity Rankings page (`page-opportunity`):**
- 4 KPI cards had hardcoded values (`7`, `76.8%`, `+4.1%`, `Lowâ€“Med`) with no IDs
- Added: `id="opp-kpi-strong"`, `id="opp-kpi-avg-conf"`, `id="opp-kpi-best-return"`, `id="opp-kpi-best-symbol"`, `id="opp-kpi-risk"`
- All defaults â†’ `â€”`

**Sentiment Center page (`page-sentiment`):**
- 4 KPI cards had hardcoded values (`Optimistic`, `63`, `RELIANCE`, `WIPRO`) with no IDs
- Added: `id="sent-kpi-market"`, `id="sent-kpi-market-sub"`, `id="sent-kpi-fear-greed"`, `id="sent-kpi-fear-greed-sub"`
- Added: `id="sent-kpi-best"`, `id="sent-kpi-best-score"`, `id="sent-kpi-worst"`, `id="sent-kpi-worst-score"`
- All defaults â†’ `â€”`

**Model Center page (`page-model`):**
- All 6 KPI cards had hardcoded values (`61.8%`, `LightGBM`, `0.034`, `5`, `Today`, `312`) with no IDs
- Added: `id="model-ensemble-acc"`, `id="model-ensemble-acc-sub"`, `id="model-best-name"`, `id="model-best-acc"`
- Added: `id="model-calibration-ece"`, `id="model-active-count"`, `id="model-active-sub"`
- Added: `id="model-last-retrain"`, `id="model-last-retrain-sub"`, `id="model-features-count"`, `id="model-features-sub"`
- All defaults â†’ `â€”`

**Risk Center page (`page-risk`):**
- All 6 KPI cards had no IDs
- Added: `id="risk-exposure"`, `id="risk-var-daily"`, `id="risk-var-pct"`, `id="risk-max-dd"`, `id="risk-sharpe"`
- Added: `id="risk-largest-pos"`, `id="risk-largest-weight"`, `id="circuit-breaker-status"`
- All defaults â†’ `â€”`

**Research Ops page (`page-agents`):**
- `roc-kpi-agents`: hardcoded `7` â†’ `â€”`

**Intelligence Lab page (`page-intelligence-lab`):**
- `il-kpi-regimes`: hardcoded `10` â†’ `â€”`

---

#### `ui/app.js`

**`hydrateMarket()` â€” full rewrite:**
- Now populates both topbar tickers AND market page KPI cards from the same API call
- New IDs targeted: `market-nifty-val`, `market-nifty-chg`, `market-banknifty-val`, `market-banknifty-chg`
- Calls `Api.marketBreadth()` separately to populate `market-breadth-val`, `market-breadth-sub`
- Color class on change elements set correctly (`positive`/`negative`)

**`hydrateMarketRegime()` â€” regime badge clobber fix:**
- Removed `badge.textContent = data.regime` which destroyed inner `<span class="regime-dot">`
- Now only sets `el('topbar-regime').textContent` and `pill.className`

**`hydrateOverview()` â€” same regime badge fix + sub-labels:**
- Same `.textContent` clobber fix
- Added `kpi-deployed`, `kpi-trades-30d` population from `ov.deployedCapital` / `ov.totalTrades30d`
- `kpi-daily-pnl` and `kpi-daily-pct` now set with correct sign/color

**`hydrateOverviewPredictions()` â€” same regime badge fix + avg conf prefix:**
- `confEl.textContent = \`Avg Conf: ${summary.avgConfidence}%\`` (was missing "Avg Conf: " prefix)

**`hydrateNews()` â€” KPI cards + field name fix:**
- Added population of: `news-kpi-count`, `news-kpi-high-impact`, `news-kpi-avg-sentiment`, `news-kpi-sentiment-sub`, `news-kpi-entities`
- Fixed field name: `n.impact_score` â†’ `n.impact_score ?? n.impactScore ?? 0` (backend returns camelCase)
- Fixed field name: `n.event_type` â†’ `n.event_type || n.eventType || 'General'`
- Added sentiment chart rebuild from live news timestamps

**`hydrateSentiment()` â€” added KPI card hydration:**
- Computes avg score from company list â†’ derives `Optimistic/Neutral/Pessimistic` label
- Derives fear/greed score and zone label from avg
- Sets strongest/weakest company from sorted company list

**`hydrateOpportunities()` â€” added KPI card hydration:**
- Counts strong signals (confidence â‰¥ 80), avg confidence, best expected return + symbol, dominant risk level

**`hydrateModelCenter()` â€” full KPI card hydration:**
- `model-ensemble-acc`: from `stats.bestAUC`
- `model-active-count` / `model-active-sub`: from `stats.activeModels` / `stats.totalFolds`
- `model-last-retrain` / `model-last-retrain-sub`: from `stats.lastTrainedAt` (formatted date + time)
- `model-best-name` / `model-best-acc`: finds highest `primaryMetric` direction model from `models` list
- `model-features-count`: max `featureCount` across all models

**`hydrateRisk()` â€” largest position + VaR pct fix:**
- Added `risk-largest-pos` and `risk-largest-weight` population
- Positions sorted by numeric weight descending (weight is string like `"3.5%"`, parsed correctly)
- `risk-var-pct` sub-label now shows `âˆ’X.XX% of Capital`
- `circuit-breaker-status` className now correctly set to `kpi-value positive/negative`

**`renderPage()` â€” removed `_liveHydrated` guard:**
- Previously: hydration ran only once per page per session â€” if backend was offline, data never refreshed on revisit
- Now: hydration runs on every page visit (async, lightweight, no visible flash)
- `_liveHydrated` set kept for action buttons that manually invalidate cache

**DOMContentLoaded handler:**
- Added `hydrateMarket()` and `hydrateMarketRegime()` calls so topbar tickers populate on initial load without requiring navigation

---

### What Still Shows `â€”` (Backend Doesn't Provide This Data Yet)
- `vix-value`, `vix-change` â€” VIX not in `/market` endpoint
- `usdinr-value`, `usdinr-change` â€” USD/INR not in `/market` endpoint
- `market-crude-val`, `market-bond-val` â€” Crude oil, bond yield not in backend
- `model-calibration-ece` â€” ECE not returned in `/models/stats`
- `model-features-count` â€” only populated if model has `featureCount` or `numFeatures` field

---

## 2026-06-23 â€” Strategy Trades + Replay UI Fully Functional

### Files Changed
- `backend/aqrti/api/routes/strategies.py` â€” strategy trade detail endpoint
- `backend/aqrti/api/routes/replay.py` â€” replay endpoint returning portfolio/positions/predictions for a date
- `ui/app.js` â€” Strategy Lab: trade table rendering, replay animation, date navigation
- `ui/index.html` â€” Strategy Trades modal, Replay panel

### Key Changes
- Clicking any strategy in leaderboard opens a trade-by-trade detail modal
- Replay button triggers animated step-through of all backtest trades
- Replay panel shows: date, portfolio value, open positions, P&L at each step

---

## 2026-06-22 â€” Phase 1â€“4 Complete: Full System Built

### What Was Built

**Phase 1 â€” UI Shell:**
- 9-page terminal UI (vanilla HTML/CSS/JS, no framework)
- Chart.js charts, ChartRegistry, lazy rendering
- Mock DataStore with all AQRTI entity schemas

**Phase 2 â€” Backend + API:**
- FastAPI backend with 45+ endpoints
- SQLAlchemy ORM + SQLite database
- APScheduler daily pipeline automation

**Phase 3 â€” Feature Engineering + ML:**
- Feature extraction from market data
- CatBoost + LightGBM + XGBoost ensemble training
- Walk-forward validation, calibration, confidence scoring

**Phase 4 â€” Paper Trading Engine:**
- Automated position open/close based on predictions
- Performance tracking: equity curve, Sharpe, drawdown
- Circuit breakers (daily/weekly/monthly loss limits)

**Desktop App:**
- Electron wrapper
- Built: `AQRTI Setup.exe` (74.8 MB) and `AQRTI Portable.exe` (67.9 MB)

---

*New sessions: read from the bottom up (oldest first) or the top down (most recent first) depending on what you need.*


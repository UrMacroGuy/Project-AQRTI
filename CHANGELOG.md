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


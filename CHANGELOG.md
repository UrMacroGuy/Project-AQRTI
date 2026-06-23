# AQRTI Changelog

> **Purpose:** Every Claude session records what was added, changed, or removed here.
> A new session should **read this file first** to catch up instantly — no need to scan the whole codebase.
>
> Format per entry:
> - **Session date** + brief title
> - Files touched
> - What changed and why

---

## 2026-06-24 — Git Agent: Auto Commit + Push on File Changes

### Files Added
- `scripts/git_agent.py` — Python watcher daemon
- `scripts/start_git_agent.bat` — double-click launcher
- `scripts/register_startup.bat` — registers agent to run at Windows login via Task Scheduler
- `scripts/unregister_startup.bat` — removes startup registration

### How It Works
1. Polls `git status --porcelain` every 30 seconds
2. Ignores: `.db-wal`, `.db-shm`, `.log`, `.pyc`, `__pycache__` (noisy runtime files)
3. Waits 120 seconds of no new changes (quiet period) before committing — batches a full coding session
4. Generates smart commit message: categorises files by folder (UI, API routes, ML, paper trading, etc.)
5. `git add <specific files>` → `git commit` → `git push origin main`
6. On Ctrl+C: commits any pending changes before exiting

### Usage
- **Run now:** Double-click `scripts/start_git_agent.bat`
- **Auto-start at login:** Run `scripts/register_startup.bat` (once, as Administrator)
- **Stop auto-start:** Run `scripts/unregister_startup.bat`
- **Tune timing:** Edit `POLL_INTERVAL` and `QUIET_PERIOD` at top of `git_agent.py`

### What Was Pushed
- The agent scripts themselves were committed and pushed as part of this session

---

## 2026-06-24 — Live Data Bug Fix: All Pages Now Show Real Backend Data

### Problem
Every KPI card, sub-label, and topbar ticker across all 14 pages showed hardcoded mock/placeholder values instead of live backend data. Root causes were:
1. HTML elements had no `id` attributes → JS hydrators' `el()` calls returned null
2. Field name mismatches (backend camelCase vs JS snake_case)
3. Hydrators never called on initial load (only on page navigation)
4. `_liveHydrated` set prevented re-hydration if backend was offline on first visit
5. `.textContent` on `.regime-badge` div destroyed inner `<span class="regime-dot">` child

---

### Files Changed

#### `ui/index.html`

**Topbar:**
- Added `id="nifty-value"`, `id="nifty-change"`, `id="banknifty-value"`, `id="banknifty-change"` to ticker spans
- Added `id="vix-value"`, `id="vix-change"`, `id="usdinr-value"`, `id="usdinr-change"` (show `—` until backend provides data)
- Fixed `id="regime-label"` → `id="topbar-regime"` (JS referenced `topbar-regime`, HTML had wrong ID)
- Regime badge container kept as `id="regime-pill"`

**Overview page (`page-overview`):**
- `kpi-portfolio`: `₹1,04,328` → `—`
- `kpi-daily-pnl`: `+₹1,284` → `—`; `kpi-daily-pct`: `+1.25%` → `—`
- Added `id="kpi-avg-conf"` to Active Predictions sub-label; default `Avg Conf: —`
- Added `id="kpi-deployed"` to Open Positions sub
- Added `id="kpi-trades-30d"` to Win Rate sub
- Added `id="kpi-knowledge-sub"` to Knowledge Score sub

**Market Intelligence page (`page-market`):**
- All 6 KPI cards previously had hardcoded values with no IDs
- Added: `id="market-nifty-val"`, `id="market-nifty-chg"`, `id="market-banknifty-val"`, `id="market-banknifty-chg"`
- Added: `id="market-breadth-val"`, `id="market-breadth-sub"`, `id="market-vix-val"`, `id="market-vix-sub"`
- Added: `id="market-crude-val"`, `id="market-crude-sub"`, `id="market-bond-val"`, `id="market-bond-sub"`
- All defaults changed from hardcoded numbers to `—`

**News Intelligence page (`page-news`):**
- 4 KPI cards had hardcoded values (`184`, `3`, `+0.48`, `67`) with no IDs
- Added: `id="news-kpi-count"`, `id="news-kpi-high-impact"`, `id="news-kpi-avg-sentiment"`, `id="news-kpi-sentiment-sub"`, `id="news-kpi-entities"`
- All defaults → `—`

**Opportunity Rankings page (`page-opportunity`):**
- 4 KPI cards had hardcoded values (`7`, `76.8%`, `+4.1%`, `Low–Med`) with no IDs
- Added: `id="opp-kpi-strong"`, `id="opp-kpi-avg-conf"`, `id="opp-kpi-best-return"`, `id="opp-kpi-best-symbol"`, `id="opp-kpi-risk"`
- All defaults → `—`

**Sentiment Center page (`page-sentiment`):**
- 4 KPI cards had hardcoded values (`Optimistic`, `63`, `RELIANCE`, `WIPRO`) with no IDs
- Added: `id="sent-kpi-market"`, `id="sent-kpi-market-sub"`, `id="sent-kpi-fear-greed"`, `id="sent-kpi-fear-greed-sub"`
- Added: `id="sent-kpi-best"`, `id="sent-kpi-best-score"`, `id="sent-kpi-worst"`, `id="sent-kpi-worst-score"`
- All defaults → `—`

**Model Center page (`page-model`):**
- All 6 KPI cards had hardcoded values (`61.8%`, `LightGBM`, `0.034`, `5`, `Today`, `312`) with no IDs
- Added: `id="model-ensemble-acc"`, `id="model-ensemble-acc-sub"`, `id="model-best-name"`, `id="model-best-acc"`
- Added: `id="model-calibration-ece"`, `id="model-active-count"`, `id="model-active-sub"`
- Added: `id="model-last-retrain"`, `id="model-last-retrain-sub"`, `id="model-features-count"`, `id="model-features-sub"`
- All defaults → `—`

**Risk Center page (`page-risk`):**
- All 6 KPI cards had no IDs
- Added: `id="risk-exposure"`, `id="risk-var-daily"`, `id="risk-var-pct"`, `id="risk-max-dd"`, `id="risk-sharpe"`
- Added: `id="risk-largest-pos"`, `id="risk-largest-weight"`, `id="circuit-breaker-status"`
- All defaults → `—`

**Research Ops page (`page-agents`):**
- `roc-kpi-agents`: hardcoded `7` → `—`

**Intelligence Lab page (`page-intelligence-lab`):**
- `il-kpi-regimes`: hardcoded `10` → `—`

---

#### `ui/app.js`

**`hydrateMarket()` — full rewrite:**
- Now populates both topbar tickers AND market page KPI cards from the same API call
- New IDs targeted: `market-nifty-val`, `market-nifty-chg`, `market-banknifty-val`, `market-banknifty-chg`
- Calls `Api.marketBreadth()` separately to populate `market-breadth-val`, `market-breadth-sub`
- Color class on change elements set correctly (`positive`/`negative`)

**`hydrateMarketRegime()` — regime badge clobber fix:**
- Removed `badge.textContent = data.regime` which destroyed inner `<span class="regime-dot">`
- Now only sets `el('topbar-regime').textContent` and `pill.className`

**`hydrateOverview()` — same regime badge fix + sub-labels:**
- Same `.textContent` clobber fix
- Added `kpi-deployed`, `kpi-trades-30d` population from `ov.deployedCapital` / `ov.totalTrades30d`
- `kpi-daily-pnl` and `kpi-daily-pct` now set with correct sign/color

**`hydrateOverviewPredictions()` — same regime badge fix + avg conf prefix:**
- `confEl.textContent = \`Avg Conf: ${summary.avgConfidence}%\`` (was missing "Avg Conf: " prefix)

**`hydrateNews()` — KPI cards + field name fix:**
- Added population of: `news-kpi-count`, `news-kpi-high-impact`, `news-kpi-avg-sentiment`, `news-kpi-sentiment-sub`, `news-kpi-entities`
- Fixed field name: `n.impact_score` → `n.impact_score ?? n.impactScore ?? 0` (backend returns camelCase)
- Fixed field name: `n.event_type` → `n.event_type || n.eventType || 'General'`
- Added sentiment chart rebuild from live news timestamps

**`hydrateSentiment()` — added KPI card hydration:**
- Computes avg score from company list → derives `Optimistic/Neutral/Pessimistic` label
- Derives fear/greed score and zone label from avg
- Sets strongest/weakest company from sorted company list

**`hydrateOpportunities()` — added KPI card hydration:**
- Counts strong signals (confidence ≥ 80), avg confidence, best expected return + symbol, dominant risk level

**`hydrateModelCenter()` — full KPI card hydration:**
- `model-ensemble-acc`: from `stats.bestAUC`
- `model-active-count` / `model-active-sub`: from `stats.activeModels` / `stats.totalFolds`
- `model-last-retrain` / `model-last-retrain-sub`: from `stats.lastTrainedAt` (formatted date + time)
- `model-best-name` / `model-best-acc`: finds highest `primaryMetric` direction model from `models` list
- `model-features-count`: max `featureCount` across all models

**`hydrateRisk()` — largest position + VaR pct fix:**
- Added `risk-largest-pos` and `risk-largest-weight` population
- Positions sorted by numeric weight descending (weight is string like `"3.5%"`, parsed correctly)
- `risk-var-pct` sub-label now shows `−X.XX% of Capital`
- `circuit-breaker-status` className now correctly set to `kpi-value positive/negative`

**`renderPage()` — removed `_liveHydrated` guard:**
- Previously: hydration ran only once per page per session — if backend was offline, data never refreshed on revisit
- Now: hydration runs on every page visit (async, lightweight, no visible flash)
- `_liveHydrated` set kept for action buttons that manually invalidate cache

**DOMContentLoaded handler:**
- Added `hydrateMarket()` and `hydrateMarketRegime()` calls so topbar tickers populate on initial load without requiring navigation

---

### What Still Shows `—` (Backend Doesn't Provide This Data Yet)
- `vix-value`, `vix-change` — VIX not in `/market` endpoint
- `usdinr-value`, `usdinr-change` — USD/INR not in `/market` endpoint
- `market-crude-val`, `market-bond-val` — Crude oil, bond yield not in backend
- `model-calibration-ece` — ECE not returned in `/models/stats`
- `model-features-count` — only populated if model has `featureCount` or `numFeatures` field

---

## 2026-06-23 — Strategy Trades + Replay UI Fully Functional

### Files Changed
- `backend/aqrti/api/routes/strategies.py` — strategy trade detail endpoint
- `backend/aqrti/api/routes/replay.py` — replay endpoint returning portfolio/positions/predictions for a date
- `ui/app.js` — Strategy Lab: trade table rendering, replay animation, date navigation
- `ui/index.html` — Strategy Trades modal, Replay panel

### Key Changes
- Clicking any strategy in leaderboard opens a trade-by-trade detail modal
- Replay button triggers animated step-through of all backtest trades
- Replay panel shows: date, portfolio value, open positions, P&L at each step

---

## 2026-06-22 — Phase 1–4 Complete: Full System Built

### What Was Built

**Phase 1 — UI Shell:**
- 9-page terminal UI (vanilla HTML/CSS/JS, no framework)
- Chart.js charts, ChartRegistry, lazy rendering
- Mock DataStore with all AQRTI entity schemas

**Phase 2 — Backend + API:**
- FastAPI backend with 45+ endpoints
- SQLAlchemy ORM + SQLite database
- APScheduler daily pipeline automation

**Phase 3 — Feature Engineering + ML:**
- Feature extraction from market data
- CatBoost + LightGBM + XGBoost ensemble training
- Walk-forward validation, calibration, confidence scoring

**Phase 4 — Paper Trading Engine:**
- Automated position open/close based on predictions
- Performance tracking: equity curve, Sharpe, drawdown
- Circuit breakers (daily/weekly/monthly loss limits)

**Desktop App:**
- Electron wrapper
- Built: `AQRTI Setup.exe` (74.8 MB) and `AQRTI Portable.exe` (67.9 MB)

---

*New sessions: read from the bottom up (oldest first) or the top down (most recent first) depending on what you need.*

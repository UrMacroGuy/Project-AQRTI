# AQRTI — Project Summary

*An outsider's understanding of the Autonomous Quant Research & Trading Intelligence platform, synthesized from the codebase, documentation, and session context.*

---

## What AQRTI Is

AQRTI is a **self-learning quant research and paper-trading platform** for the Indian stock market (NSE/BSE). It is a full-stack application built as a desktop/browser dashboard on top of a Python backend that runs an autonomous daily pipeline.

**Core philosophy:**
- "Survive First. Profit Second."
- "Backtests can lie. Markets do not."
- "AQRTI does not predict prices. AQRTI ranks opportunities."

**What it is NOT:** A real-money trading bot. Every trade is virtual (₹1,00,000 starting balance). It is a *research validation platform* — the entire point is to prove, with honest statistics, whether an automated strategy has a real edge before a human ever risks real money on it.

---

## Architecture Overview

```
Project AQRTI/
├── ui/                  Frontend: vanilla HTML/CSS/JS + Chart.js (no framework)
│   ├── index.html       Structure — all 14 dashboard page sections
│   ├── style.css        Presentation — Bloomberg-terminal theme
│   ├── app.js           Logic — navigation, hydration, chart rendering (~5,000 lines)
│   └── api.js           API layer — talks to FastAPI on localhost:8000
├── backend/             Python (FastAPI + SQLAlchemy + SQLite)
│   ├── main.py            Thin entrypoint
│   ├── aqrti/             Core app: API routes, DB models, config, scheduler
│   ├── ml/                Model training + inference (CatBoost, NGBoost, AQRTINet)
│   ├── strategies/        Genetic-algorithm Strategy Arena
│   ├── paper_trading/     Virtual portfolio simulation + forward-quarantine testing
│   ├── learning/          Self-learning loop: failure analysis, calibration, drift
│   ├── agents/            7 autonomous research agents + CRO daily brief
│   ├── sentiment/         News NLP + sentiment scoring
│   ├── news/              RSS ingestion + entity/event extraction
│   ├── features/          Feature engineering (62+ features per stock)
│   ├── data_supremacy/    FII/DII flows, options PCR, breadth, sector rotation
│   ├── intelligence/      Phase-9 self-improvement modules
│   ├── intelligence_training/  Historical replay + meta-learning pipeline
│   ├── arena/             Strategy head-to-head battles, replay animation
│   ├── portfolio/         Portfolio construction, position sizing, rebalancing
│   ├── vault/             Daily archive/snapshot/backup + date replay
│   └── scripts/           One-off maintenance/migration scripts
├── plans/                 Original design docs (aspirational, Version 1.0 — historical only)
├── docs/                  Ground-truth technical docs (current state)
└── graphify-out/          Knowledge graph artifacts
```

**Tech Stack:**
| Layer | Technology |
|---|---|
| UI | Vanilla HTML5 + CSS3 + ES2022 (no framework) |
| Charts | Chart.js 4.4 |
| Desktop | Electron (`AQRTI Setup.exe`, `AQRTI Portable.exe`) — stale, use browser UI |
| API | Python FastAPI + Uvicorn |
| Database | SQLite via SQLAlchemy ORM, WAL mode (~3.1 GB) |
| ML | CatBoost, NGBoost, AQRTINet (custom) — LightGBM/XGBoost removed 2026-06-27 |
| Data sources | yfinance, feedparser (RSS), NSE bhavcopy CDN, httpx, Finnhub |
| Scheduler | APScheduler — cron + interval jobs |

---

## The 14-Page Dashboard

| # | Page | What it shows |
|---|---|---|
| 1 | **Overview** | Portfolio value, daily P&L, market regime, top predictions, equity curve |
| 2 | **Market Intelligence** | NIFTY 50, BANKNIFTY, VIX, USD/INR, crude, gold, sector strength, breadth |
| 3 | **Opportunity Rankings** | All predictions ranked by confidence + expected return, risk level |
| 4 | **News Intelligence** | Impact Score (>75 = critical), sentiment, high-impact feed |
| 5 | **Sentiment Center** | Market score (<40 fear / >60 greed), company + sector sentiment |
| 6 | **Strategy Lab** | Leaderboard by fitness, evolution tree, graveyard, DNA viewer, replay |
| 7 | **Model Center** | ML registry, direction accuracy, AUC, walk-forward folds, calibration |
| 8 | **Learning Center** | Knowledge/Intelligence Score (0–100), failure analysis, lessons, feature decay |
| 9 | **Research Ops** | The 7 research agents + CRO, daily brief, pipeline health |
| 10 | **Paper Trading** | Open positions, equity curve, trade history, analytics |
| 11 | **Risk Center** | Exposure %, VaR, drawdown, sector limits, circuit breaker status |
| 12 | **Intelligence Vault** | Date replay (exactly what AQRTI knew/held on any past day) |
| 13 | **Intelligence Lab** | Regime datasets, meta-learning insights, feature proposals |
| 14 | **Data Intelligence** | Data Quality Score, FII/DII, options PCR/max pain, earnings calendar |

**Plus:** Go / No-Go page (GO-1) — 5-condition money-readiness scorecard.

---

## Core Subsystems

### 1. Data Layer

**Seven conceptual layers:**
1. Market data — OHLCV, adjusted close, VWAP, delivery volume, trade count, market cap
2. Index data — NIFTY, BANKNIFTY, 12 sector indices
3. Corporate events — results, dividends, bonuses, splits, M&A, board meetings
4. News data — RSS-ingested articles
5. Sentiment data — news/social/analyst/forum sentiment with confidence/virality/velocity
6. Derivatives data — open interest, OI change, put-call ratio, max pain, build-ups
7. Macro data — repo rate, inflation, GDP, USD/INR, crude, gold, bond yields, VIX

**Universe (verified 2026-07-05):**
- **884** total tracked symbols | **393** active | **352** backtest-eligible
- 5 years of price history per symbol (820k+ rows)
- Feature store: 62 engineered features per symbol per day, 16.7M+ feature rows total

### 2. ML Prediction Engine (AQRTINet v3.1 → v4.0)

| Model | Role |
|---|---|
| **CatBoost** | Primary gradient-boosted-tree direction/return model |
| **NGBoost** | Calibrated probability estimates (well-formed confidence intervals) |
| **AQRTINet v4.0** | In-house model: regime-aware mixture of experts, cross-sectional percentile ranking, 7-fold OOF stacking, Platt calibration |

**v4.0 SOTA upgrades (2026-07-06):**
- **P0-A:** Feature Neutralization (Numerai-style — OLS-project features against beta + sector return)
- **P0-B:** Triple-Barrier Labels (dynamic TP/SL via ATR14)
- **P0-C:** Era-Boosted Training (60-day eras, upweight hard eras 3×)
- **P0-D:** Rolling IC Retrain Trigger (emergency retrain when IC < 0.01 for 3 days)
- **P1-A:** FII/DII Flow Features (6 new market features)
- **P1-B:** Conformal Prediction Intervals (split-conformal, coverage-guaranteed)
- **P1-D:** Adversarial Sample Augmentation (2× training data with Gaussian perturbations)
- **P1-E:** Purged Embargo CV (removes label-window overlap between train/test)
- **P2-A:** Sector Peer-Mean Graph Propagation (approximates HIST's GNN without GPU)

**Removed (2026-06-27):** LightGBM (49.04% accuracy, worse than coin flip) and XGBoost (47.69%, actively anti-predictive).

### 3. Strategy Arena — Genetic Algorithm Engine

**The 7-step closed loop:**
Generate candidates (10 DSL families) → backtest against 5yr / ~50-stock NSE history → score with 6-dimension Fitness formula (0–100) → promote/retire via state machine → evolve via mutation/crossover → learn from failures → adapt weights/floors automatically.

**Lifecycle state machine:**
```
candidate → shadow → promoted → [active]*  (*requires human approval)
                    ↘ retired → graveyard
```

**Promotion gates (ALL must pass):**
- fitness ≥50.0
- trade_count ≥60
- win_rate ≥52%
- sharpe ≥0.5 (honest mark-to-market)
- OOS pass (6-month holdout, ≥5 trades, ≥50% WR, positive expectancy)
- Benchmark gate: Sharpe ≥0.8× buy-and-hold NIFTY50
- Duplicate gate: Jaccard similarity <60% with any already-promoted strategy
- **Quarantine gate (GO-8):** promoted ≥60 days + ≥20 closed shadow trades + ≥50% WR + positive net P&L

**Current honest baseline (2026-07-05):** **0 promoted algos out of 927 population.** Every algo has negative honest Sharpe. That is **correct behavior, not a bug** — the fixed, honest backtester says the current population has not yet proven an edge.

### 4. Paper Trading Engine

- **Starting capital:** ₹1,00,000 virtual
- **Position sizing:** confidence-based (90%+ → 5%, down to 60–69 → 1%, below 60 → no trade)
- **Continuous monitoring:** every 5 minutes against live prices (Finnhub primary, yfinance fallback)
- **Strategy shadow runner:** every promoted/active strategy gets its own independent virtual book for forward-quarantine evidence

### 5. Risk Engine & Circuit Breakers

| Trigger | Limit |
|---|---|
| Daily loss | −3% of portfolio |
| Weekly loss | −6% of portfolio |
| Monthly loss | −12% of portfolio |

- Position limits: 2–5% initial, 10% max per position; 25% max sector; 80% max total exposure
- Regime-based posture adjustments
- Risk metrics: Sharpe, Sortino, Max Drawdown, VaR, Profit Factor

### 6. Self-Learning System

Daily 8-step process (`learning/learning_loop.py`):
1. Prediction Outcome Backfill
2. Pattern Outcome Evaluation
3. Failure Analysis & Classification
4. Model Drift Detection + Auto-Retrain
5. Confidence Scaling (ECE correction)
6. Feature Decay Detection
7. Pattern Memory Sync
8. Daily Knowledge Score (8-component weighted composite, 0–100)

### 7. Research Agents

| Agent | Role |
|---|---|
| Market Research | Macro conditions, breadth, sector rotation, regime |
| Pattern Research | Recurring price patterns across the NSE universe |
| Strategy Research | Discovers/tests new strategies, decay detection |
| Model Research | ML performance, drift, feature importance |
| News Research | Reads and scores news for market impact |
| Risk Research | Portfolio concentration, tail risk, drawdown |
| **CRO** (Chief Research Officer) | Synthesises all 6 agents into the Daily Intelligence Brief |

---

## The Database

SQLite (`backend/aqrti.db`, several GB, WAL mode) with **93 tables** grouped by subsystem:

**Key table groups:**
- **Core Market:** Stock, DailyPrice, IndexData, CorporateEvent, NewsEvent, SentimentRecord
- **Portfolio & Features:** PortfolioSnapshot, FeatureMetadata, FeatureValue (largest table — 18.5M+ rows), MarketRegime
- **Model Management:** ModelVersion, ModelMetric, WalkForwardFold, PatternMatch
- **Paper Trading:** PaperPortfolio, PaperPosition, PaperTrade, EquityCurvePoint
- **Strategy Arena:** StrategyV2 (main population), StrategyPerformance, StrategyEvolutionHistory, StrategyGraveyard
- **Agents:** Agent, AgentTask, AgentReport, ResearchBrief, ResearchFinding
- **Data Supremacy:** FIIDIIFlow, OptionsChain, MarketBreadth, SectorRotation
- **Index Futures (parallel):** IndexFuturesContract, IndexFuturesPrice, IndexFuturesRoll, IndexFuturesFeatureValue
- **Phase 9 Intelligence:** DiscoveredRegime, StrategyDNA, KnowledgeNode, KnowledgeEdge, etc.

---

## Daily Pipeline

**Boot sequence** (runs when backend starts): market data → features → news → sentiment → predictions → paper trading → learning loop.

**Scheduled jobs:**
| Job | Frequency | What it does |
|---|---|---|
| Main daily job | 15:30 IST weekdays | Full 18-step pipeline |
| Hourly agent job | Every 1 hour | 7-agent research pipeline + CRO brief |
| Strategy loop | Every 5 minutes | Micro-evolution (generate/backtest/evolve) |
| Alert check | Every 5 minutes | Drawdown / Knowledge Score warnings |
| Arena job | Every 1 hour | Champion grading + refinement |
| Integrity sweep | Weekly, Sat 10:00 | Split-adjustment drift detection/healing |
| Paper monitor | Every 5 minutes + boot | SL/TP/max-hold checks, new positions |
| Weekly backup | Saturday 08:00 | SQLite `.backup` + integrity check + prune to 7 |

---

## The Trust Overhaul (2026-07-01 to 07-02)

The most consequential phase in the project's history. Discovered that every stored strategy metric was inflated due to:
- Sharpe/Sortino computed from average per-day return repeated across holding period (artificially collapsing variance)
- Stop-loss/take-profit checked against close only (not intrabar)
- DSL evaluator silently fell back to generic rules when features were missing
- Same-day ML predictions used in backtests (look-ahead bias)
- US transaction costs (0.10%) applied to Indian stocks instead of NSE costs (0.28%)

**Fix:** rebuilt the backtester for honest mark-to-market Sharpe, fail-closed DSL, correct costs, and added: OOS gate, benchmark gate, duplicate gate, forward-paper quarantine, and liquidity filter (≥₹5cr daily turnover).

**Result:** of ~700 strategies with ≥60 trades, only ~12% showed genuinely positive honest Sharpe. The current 0/927 promoted baseline is the correct, expected state.

---

## Road to Real Money (Master Roadmap)

Organized into stages with exit criteria:

**Stage 0 — Trust floor ✅ (complete as of 2026-07-05)**
- Honest backtester, no fabricated data, docs synced to code

**Stage 1 — Reliability ✅ (complete as of 2026-07-05)**
- Watchdog + auto-restart (GO-2) ✅
- Silent-failure alarm (GO-3) ✅
- Alert channel outside dashboard — Telegram (GO-4) ✅
- 37-test suite, all passing (ARCH-2) ✅
- Scheduler split from API process (ARCH-4) ✅
- Migration framework (ARCH-3) ✅
- Weekly backup + integrity check (ARCH-9) ✅
- *Exit criteria:* 30 consecutive trading days of pipeline completion with zero manual intervention

**Stage 2 — Edge (in progress)**
- Population diagnosis (GO-5) ✅ — verdict: win-rate collapse (median WR 47.1%), root cause: DSL generates random-walk-frequency signals
- Search-space upgrades (GO-5b) ✅ — added 3 new DSL families + 5 new regime features
- Evolution honesty check (GO-5c) ✅ — PASS WITH WARNINGS
- Index-futures segment maturation — ongoing
- *Exit criteria:* ≥1 algo legitimately promoted, or written evidence-backed conclusion about next search direction

**Stage 3 — Human workflow (pending)**
- Morning Decision Screen (GO-7)
- Quarantine progress board (GO-8) ✅ — implemented on Go/No-Go page
- UI truth-and-polish pass (GO-9)
- My Portfolio module (PF-1..PF-6)
- ARCH-5: split `app.js` monolith into per-page modules

**Stage 4 — Real-money bridge (only after Stages 1-3)**
- Go/No-Go scorecard (GO-1) ✅ — live in UI, all 5 conditions correctly red
- Paper-vs-real reconciliation (GO-6)
- Real-capital risk rails (GO-10) ✅ — documented in UI
- Monthly review ritual (GO-11)
- *First real capital: ₹5,000 max, one algo only, position cap ₹1,000*

**Stage 5 — Later / deferred:**
- Broker read-API import (Zerodha Kite Connect) · options/derivatives algos · cloud hosting · two-way Obsidian · ARCH-6/10/11

---

## Key Files & Their Authority

| File | Role | When it disagrees with anything else, it wins |
|---|---|---|
| `backend/strategies/promotion_config.py` | ALL promotion/retirement/quarantine gate constants | #1 — never re-declare these elsewhere |
| `CHANGELOG.md` (top 2–3 entries) | Session history, newest first | #2 — read at every session start |
| `plans/PROJECT_DIARY.md` | Full-system reference | #3 |
| `plans/DATABASE_AND_TRAINING.md` | Schema + training pipeline | #3 |
| `docs/STRATEGY_ARENA.md` | Arena engine reference | #4 (constants can lag config) |
| `plans/*.md` | Historical design docs (June 2026) | #5 — do NOT trust their numbers |
| `IMPROVEMENTS.md` | Active backlog / task queue | #6 — work from here |

---

## Hard Rules (Non-Negotiable)

1. **No placeholder, mock, or fabricated data — anywhere, ever.**
   - If a data source is unavailable, the UI shows "NO DATA — source unavailable"
   - Synthetic data allowed only if flagged (`is_synthetic=True`) AND labeled
2. **Honest metrics only.** Never loosen a gate, cap, or cost model to make results look better. No look-ahead bias. NSE costs 0.28% round-trip. If a metric looks too good (AUC ≈ 1.0, Sharpe > 3), treat it as a bug.
3. **Verify, don't assume.** After any fix: check the DB, hit the endpoint, read the log. CHANGELOG entries record verified reality, including failures.

---

## Running the System

- **Backend:** `cd backend && .venv\Scripts\activate && python main.py` → port 8000, Swagger at `/docs`, health at `/health`
- **UI:** `npm run dev` → port 3000
- **Scheduler:** daily pipeline cron 15:30 IST weekdays; algo micro-loop every 5 min; agents hourly; integrity sweep Sat 10:00 IST
- **Lite mode:** `AQRTI_LITE_MODE=1` disables heavy loops (RAM 800MB+ → ~230MB)

---

## Personal Portfolio Module (Planned, Not Built)

Tracks the user's real 60-40 investment plan (₹2,000/month, Zerodha + INDmoney):
- India 60%: Nifty 50 Index Fund (₹600/mo), quarterly stocks (TCS/INFY/HDFCBANK/RELIANCE ₹300 each), Smallcap 250 Fund (₹200/mo), Gold ETF (₹100/mo)
- US 40%: VTI (₹400/mo), PLTR (₹250/mo), LMT (₹150/mo)

**Rules:** tracker + advisor ONLY. No broker write APIs, no auto-execution. Real-money tables never mix with paper trading. Mutual funds valued at prior-day AMFI NAV (always labeled as such).

---

## Obsidian Integration (Built, Active)

One-way exporter renders DB knowledge into an Obsidian vault outside the repo (`Desktop/AQRTI Vault/`). DB stays source of truth; vault is derived/regenerable.

**Phase 1 (done):** Daily / Stock / Lesson / Home / Algo / Report notes with YAML frontmatter, wikilinks, Dataview index notes, CSS theming.
**Phase 1.5 (done):** Algo notes, Report notes with deduplication.
**Phase 2 (blocked):** Portfolio notes — waiting on Personal Portfolio module.
**Phase 3 (deferred):** Two-way vault-inbox → agent research tasks (needs spec first).

---

## Current State Snapshot (2026-07-06)

| Metric | Value |
|---|---|
| Population | 927 algos |
| Promoted | **0** (correct — no algo has proven an edge yet) |
| Backtest-eligible universe | 352 symbols |
| Feature rows | 16.7M+ |
| Test suite | 37/37 passing |
| Stage | Stage 1 complete, Stage 2 in progress |
| Last significant work | AQRTINet v4.0 SOTA upgrades (conformal prediction, era-boosting, feature neutralization, peer-mean propagation, adversarial augmentation, FII features, triple-barrier labels, rolling IC trigger, purged CV) |

---

*This summary was generated on 2026-07-06 from a read-through of the codebase, documentation, and session context. For the most current ground truth, always check `CHANGELOG.md` (top entries) and the code itself — especially `backend/strategies/promotion_config.py`.*

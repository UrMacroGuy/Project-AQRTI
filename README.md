# AQRTI Intelligence Terminal

> AI-powered stock market intelligence system for the Indian market (NSE/BSE) — built as a self-learning, autonomous research and paper-trading engine.

---

## What is AQRTI?

AQRTI is a full-stack intelligence terminal that acts like a team of analysts working around the clock. It reads live news, scores sentiment, trains ML models, discovers trading algos through evolution, manages a paper portfolio, and summarises everything into a clean dashboard — all autonomously.

It is **not** a trading bot with real money. It is a research and validation platform: everything runs on paper capital (₹1,00,000 virtual) so you can validate an edge before committing real funds.

---

## Screenshots

> Terminal runs as a desktop Electron app or in-browser via `npm run dev`.

| Overview | Opportunity Rankings | Algo Lab |
|---|---|---|
| Portfolio value, regime, top predictions | Ranked signals with confidence bars | Leaderboard, evolution tree, replay |

| Model Center | Risk Center | Intelligence Vault |
|---|---|---|
| ML model registry, accuracy, calibration | VaR, drawdown, circuit breakers | Date replay, research archive |

---

## Current State

AQRTI went through a **Trust Overhaul** in July 2026: the backtester, feature
pipeline, arena, and promotion gates were rebuilt to eliminate several
sources of inflated/dishonest metrics (lookahead bias, unrealistic costs,
a truncated feature window, ungated arena promotion). The honest baseline
this produced is intentionally strict — as of the overhaul, **no algo has
yet re-proven an edge** under the fixed gates, and the population is
rebuilding from scratch under real conditions.

Live population size, promotion counts, fitness scores, and Intelligence
Score change by the hour as evolution runs — this README does not
hardcode them. **See the live dashboard (Overview + Algo Lab pages) for
current numbers**, or `GET /overview` / `GET /strategies` via the API.

Gate logic (fitness/win-rate/Sharpe/OOS/benchmark/duplicate-overlap/
drawdown thresholds) lives in `backend/strategies/promotion_config.py` —
that file is the single source of truth if any doc disagrees with it.

---

## Key Features

| Feature | Description |
|---|---|
| **14-page Intelligence Terminal** | Full dashboard: Overview, Market, Opportunities, News, Sentiment, Algo Lab, Model Center, Learning, Agents, Paper Trading, Risk, Vault, Intelligence Lab, Data Intelligence |
| **Live Market Data** | NIFTY 50, BANKNIFTY, sector strength, top movers via yfinance |
| **Global Universe** | 779 stocks tracked: 309 Indian (137 NSE + 172 BSE), plus US, UK, EU, JP, HK, KR, AU, CA — see PROJECT_DIARY.md §4 for the tracked-vs-active-vs-backtest-eligible distinction |
| **ML Prediction Engine** | CatBoost + NGBoost ensemble + AQRTINet v3.1 — trained on features across all active symbols |
| **Strategy (Algo) Evolution** | Genetic algorithm: 11 families, 9 mutation ops, 6-dimension fitness scoring, runs every 5 min |
| **7 Research Agents** | Market, Pattern, Algo, Model, News, Risk agents + CRO daily brief |
| **Paper Trading Engine** | Fully automated open/close positions based on best algo + confidence threshold |
| **Self-Learning System** | Tracks failures, extracts lessons, adapts confidence calibration — see dashboard for current knowledge score |
| **Intelligence Vault** | Full date-replay: see exactly what AQRTI knew and held on any past date |
| **Data Intelligence** | FII/DII flows, options PCR, market breadth, earnings calendar, corporate filings |
| **Risk Engine** | VaR, Sharpe, drawdown history, sector exposure limits, circuit breakers |

---

## Architecture

```
Project AQRTI/
├── ui/
│   ├── index.html          ← Single-page shell: all 14 page sections
│   ├── style.css           ← Terminal design system (CSS custom properties)
│   ├── app.js              ← Navigation, charts, live hydration functions
│   └── api.js              ← API layer — all calls to FastAPI backend
│
├── backend/
│   ├── main.py             ← FastAPI app entry point + APScheduler jobs
│   ├── aqrti/
│   │   ├── api/routes/     ← REST API endpoints across 59 route files (see /docs for the full live list)
│   │   ├── database/       ← SQLAlchemy models + SQLite engine
│   │   └── data/           ← Market data fetchers, portfolio helpers
│   ├── ml/                 ← Model training, feature engineering, walk-forward
│   ├── intelligence_training/ ← Regime datasets, meta-learning, model memory
│   ├── paper_trading/      ← Paper engine, execution, performance tracking
│   ├── strategies/         ← Algo evolution engine (genetic algorithm)
│   ├── learning/           ← Failure analysis, lessons, knowledge scoring
│   ├── sentiment/          ← News NLP, sentiment scoring, velocity tracking
│   ├── data_supremacy/     ← FII/DII, breadth, sector rotation, options
│   ├── agents/             ← 7 research agents + daily brief generator
│   ├── vault/              ← Snapshot archiving, replay, backup
│   ├── news/               ← RSS ingestion + article processing
│   └── features/           ← Feature store, proposal system
│
├── plans/                  ← Architecture docs for each engine
├── AQRTI_USER_GUIDE.md     ← Plain-English guide for non-technical users
├── CHANGELOG.md            ← Session-by-session change log
└── package.json            ← npm scripts: dev server + backend launcher
```

### Three-Layer UI Architecture

```
index.html   →  Structure Layer      (semantic HTML, all page sections)
style.css    →  Presentation Layer   (CSS tokens — swap entire theme in :root {})
app.js       →  Logic Layer
               ├── ChartRegistry     → Owns all Chart.js instances, prevents canvas errors
               ├── Page Renderers    → One function per page, fully independent
               ├── Hydration Layer   → Async live-data fetchers called on page visit — no mock/fallback data; empty states render explicitly when the API has nothing
               └── Navigation        → Re-hydrates on every visit (no stale cache)
api.js       →  API Layer            → apiFetch / apiPost → localhost:8000/api/v1
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **UI** | Vanilla HTML5 + CSS3 + ES2022 (no framework) |
| **Charts** | Chart.js 4.4 |
| **Fonts** | JetBrains Mono + Inter |
| **Desktop** | Electron (AQRTI Setup.exe / AQRTI Portable.exe) |
| **API** | Python FastAPI + Uvicorn |
| **Database** | SQLite via SQLAlchemy ORM |
| **ML Models** | CatBoost, NGBoost, AQRTINet v3.1 (custom regime-mixture-of-experts), scikit-learn |
| **Data** | yfinance, feedparser (RSS), httpx |
| **Scheduler** | APScheduler (daily pipeline automation) |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1 — Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

Backend starts at `http://localhost:8000`. Swagger docs at `/docs`.

### 2 — Frontend (Browser)

```bash
npm run dev
# Opens at http://localhost:3000
```

### 3 — Desktop App

Use the pre-built installer from `dist/installers/`:
- `AQRTI Setup.exe` — installs to Program Files
- `AQRTI Portable.exe` — no install, run anywhere

---

## API Reference

All endpoints live under `http://localhost:8000/api/v1/`. Selected endpoints:

| Endpoint | Description |
|---|---|
| `GET /overview` | Portfolio value, regime, KPIs |
| `GET /market` | NIFTY, BANKNIFTY, sector strength, top movers |
| `GET /predictions` | Ranked prediction signals |
| `GET /news` | Scored news articles |
| `GET /sentiment` | Company + sector sentiment scores |
| `GET /strategies` | Algo leaderboard |
| `GET /models` | ML model registry |
| `GET /risk` | VaR, drawdown, circuit breakers, positions |
| `GET /paper-portfolio` | Paper trading state |
| `GET /paper-trades` | Trade history |
| `POST /admin/train` | Trigger full model retrain |
| `POST /admin/predict` | Run prediction pipeline |
| `POST /admin/intelligence` | Run full 12-step intelligence pipeline |
| `POST /admin/paper-trade` | Execute paper trades |
| `GET /replay/{date}` | Vault date replay |

Full list: `http://localhost:8000/docs`

---

## The Daily Pipeline (Automated)

AQRTI runs a 12-step intelligence pipeline daily after market close:

```
1. Ingest market data (yfinance)
2. Ingest news (RSS feeds)
3. Score sentiment (NLP)
4. Update market breadth + FII/DII
5. Build feature vectors
6. Run ML predictions (ensemble)
7. Execute paper trades
8. Run algo evolution (genetic algorithm)
9. Score failures + extract lessons
10. Update knowledge score
11. Run research agents + generate daily brief
12. Archive vault snapshot + backup
```

Trigger manually: `POST /admin/intelligence`

---

## Dashboard Pages

| # | Page | What It Shows |
|---|---|---|
| 1 | **Overview** | Portfolio value, daily P&L, regime, top predictions, equity curve |
| 2 | **Market Intelligence** | NIFTY/BANKNIFTY, breadth, sector strength, top movers |
| 3 | **Opportunity Rankings** | All predictions ranked by confidence + expected return |
| 4 | **News Intelligence** | High-impact events, sentiment trend, full news feed |
| 5 | **Sentiment Center** | Company + sector sentiment scores, velocity, fear/greed |
| 6 | **Algo Lab** | Leaderboard, evolution tree, regime affinity, graveyard, replay |
| 7 | **Model Center** | ML model registry, accuracy, calibration curve, walk-forward |
| 8 | **Learning Center** | Knowledge score, failures, lessons, drift, feature intelligence |
| 9 | **Research Ops** | 7 research agents, daily brief, agent health, pipeline status |
| 10 | **Paper Trading** | Open positions, equity curve, trade history, analytics |
| 11 | **Risk Center** | Exposure, VaR, drawdown, sector limits, circuit breakers |
| 12 | **Intelligence Vault** | Date replay, research archive, backups |
| 13 | **Intelligence Lab** | Regime datasets, meta-learning, feature proposals, model memory |
| 14 | **Data Intelligence** | FII/DII, options intelligence, breadth, earnings calendar |

---

## Understanding Confidence Scores

| Confidence | Meaning |
|---|---|
| **90%+** | Very high conviction — rare, strongest signals |
| **75–90%** | High confidence — core paper trading threshold |
| **60–75%** | Moderate — worth watching, not auto-traded |
| **Below 60%** | Low — filtered out by default |

---

## Key Metrics to Monitor

| Metric | Target | Warning |
|---|---|---|
| Intelligence Score | 70+ | Below 60: predictions unreliable |
| Model Direction Accuracy | 65%+ | Below 60%: use caution |
| Paper Win Rate | 55%+ | Below 45%: algo failing |
| Sharpe Ratio | 1.0+ | Below 0.5: poor risk-adjusted return |
| Max Drawdown | < 10% | Above 15%: circuit breakers risk |
| VIX | < 15 | Above 20: high fear, reduce exposure |
| Data Quality Score | 80%+ | Below 70%: predictions less reliable |

---

## Circuit Breakers

AQRTI automatically pauses paper trading if:

| Trigger | Limit |
|---|---|
| Daily loss | −3% of portfolio |
| Weekly loss | −6% of portfolio |
| Monthly loss | −12% of portfolio |

When triggered: status shows `TRIGGERED` on Risk Center and Overview.

---

## Research Agents

| Agent | Role |
|---|---|
| Market Research | Analyses macro conditions, breadth, regime |
| Pattern Research | Finds recurring price patterns in NSE universe |
| Algo Research | Discovers and tests new trading algos |
| Model Research | Evaluates ML model performance and drift |
| News Research | Reads and scores news for market impact |
| Risk Research | Assesses portfolio concentration and tail risk |
| CRO (Chief Research Officer) | Synthesises everything → Daily Intelligence Brief |

---

## Glossary

| Term | Definition |
|---|---|
| **AUC** | Area Under Curve — model accuracy (0.5 = random, 1.0 = perfect) |
| **Backtest** | Testing an algo on historical data |
| **Circuit Breaker** | Auto-stop trading if loss exceeds threshold |
| **Drawdown** | Drop from portfolio peak |
| **ECE** | Expected Calibration Error — confidence vs actual accuracy gap |
| **Equity Curve** | Portfolio value over time chart |
| **FII/DII** | Foreign/Domestic Institutional Investors |
| **Fitness Score** | AQRTI's combined algo rating (returns + Sharpe + drawdown) |
| **Graveyard** | Retired failed algos — studied to prevent repeat mistakes |
| **P&L** | Profit & Loss |
| **PCR** | Put-Call Ratio — >1.2 bearish, <0.8 bullish |
| **Regime** | Market condition: BULL, BEAR, SIDEWAYS, VOLATILE, RECOVERY |
| **Sharpe Ratio** | Return per unit of risk (>1.0 good, >2.0 excellent) |
| **VaR** | Value at Risk — worst expected daily loss |
| **Walk-Forward** | Train on past, test on future — rigorous model validation |
| **Win Rate** | % of trades that were profitable |

---

## Disclaimer

AQRTI is a research and paper-trading tool. It does not execute real trades or manage real money. Nothing in this system constitutes financial advice. Past performance of paper algos does not guarantee future results.

---

*Built for the Indian market (NSE/BSE). Powered by FastAPI + SQLite + CatBoost/NGBoost/AQRTINet + Chart.js.*

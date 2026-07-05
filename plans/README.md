# AQRTI Intelligence Terminal

> Self-learning quant research & paper-trading platform for Indian markets (NSE/BSE).
> No real money. No faked results. No look-ahead bias. Everything traces to a real DB row.

---

## What It Is

AQRTI is a full-stack intelligence terminal that runs like a team of analysts working around the clock on NSE/BSE data. Every night after market close, a 12-step pipeline ingests prices, scores news sentiment, retrains ML models, evolves trading algos through a genetic algorithm, and archives a complete snapshot — all autonomously. The UI surfaces everything in a 14-page browser dashboard.

**What it does not do:** execute real trades, manage real money, or fabricate data. When a data source is unavailable, the system says so explicitly. An honest gap beats a plausible lie.

---

## Trust Architecture

AQRTI went through a complete **Trust Overhaul in July 2026**. Before the overhaul, the system had inflated metrics from:

- Lookahead bias in feature computation (features using future prices)
- US transaction costs applied to NSE trades (wildly underestimated friction)
- Fail-open DSL evaluation (missing features → trade entered anyway)
- No out-of-sample holdout, no benchmark gate, no duplicate filter

**The overhaul rebuilt every one of these.** The result: **0 of 927 algos currently promoted** — a population that grew under the old, dishonest gates and must now re-prove an edge under honest ones. This is correct behavior, not a bug. The system is working.

Gate logic lives in `backend/strategies/promotion_config.py` — the single source of truth.

```
Algo promotion requires ALL of:
  ├── Honest backtest gates (Sharpe, win rate, drawdown, NSE costs 0.28% round-trip)
  ├── Out-of-sample holdout pass (held-out final 20% of data)
  ├── Benchmark gate (≥ 0.8× NIFTY buy-and-hold Sharpe)
  ├── Duplicate gate (< 70% trade overlap with any promoted algo)
  └── Forward paper quarantine (≥ 60 days, ≥ 20 shadow trades, ≥ 50% win rate, positive P&L)
                                  └── Human approval  ← last gate, never the first
```

---

## AQRTINet v4.0 — The Prediction Model

AQRTINet is a custom ML model built for NSE/BSE 5-day direction prediction. Version 4.0 added 9 SOTA improvements over v3.1 in July 2026.

### Architecture

```
Raw Features (71 registered)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  P0-A  Feature Neutralization (Numerai-style OLS)           │
│        Residualizes each feature against market beta        │
│        (beta_21d) + sector return (sector_return_5d)        │
│        → isolates stock-specific alpha signal               │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  PercentileRanker  (cross-sectional, per-date)              │
│  Converts absolute feature values to within-date ranks      │
│  so RELIANCE RSI=65 becomes "top 20% of universe today"     │
└───────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   Interaction      P1-D Adversarial  P1-E Purged
   Features         Augmentation      Embargo CV
   (cross-feature   (2× training      (purge 5-day
    products by IC) data + Gaussian   label-window
                    noise σ=0.05×std) contamination)
        └───────────────┼───────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Regime Router  →  4 × Regime Expert (BULL/BEAR/SIDEWAYS/   │
│                    VOLATILE)                                 │
│                                                             │
│  Each expert: HistGradientBoostingClassifier                │
│    + asymmetric loss proxy (class_weight {DOWN:2, UP:1})    │
│    + P0-C era-boosted training (60d eras, 3× upweight on    │
│              bottom-quartile IC eras over 2 rounds)         │
│    + IC-based feature selection per regime                  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Platt Calibration  (original data only, not augmented)     │
│  +                                                          │
│  P1-B Conformal Prediction Intervals                        │
│       Split-conformal quantiles from OOF residuals          │
│       predict_interval(X, α=0.10) → (n,2) coverage-        │
│       guaranteed probability bounds — no MAPIE dependency   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
             P(UP) + [lower, upper] interval
             → confidence score → trade / no trade
```

### v4.0 Improvements

| ID | Improvement | Where | What It Fixes |
|---|---|---|---|
| **P0-A** | Feature Neutralization | `aqrtinet_model.py` | Removes market beta + sector return from every feature; exposes stock-specific alpha only |
| **P0-B** | Triple-Barrier Labels | `label_generator.py` | ATR14-dynamic TP (1.5×ATR) / SL (1.0×ATR) barriers replace fixed-% labels; NEUTRAL outcomes preserved as None |
| **P0-C** | Era-Boosted Training | `aqrtinet_model.py` | 60-day eras scored by Spearman IC; bottom-quartile eras upweighted 3× — forces learning hard market periods |
| **P0-D** | Rolling IC Retrain | `model_retrainer.py` | 20-day rolling IC between predicted confidence and actual outcome; IC < 0.01 for 3 days → emergency retrain |
| **P1-A** | FII/DII Flow Features | `fii_features.py` | 6 institutional flow features from `fii_dii_flows` table; point-in-time safe; None if table empty (no imputation) |
| **P1-B** | Conformal Intervals | `aqrtinet_model.py` | Split-conformal quantiles from Platt OOF residuals; coverage-guaranteed bounds; pure numpy |
| **P1-D** | Adversarial Augmentation | `aqrtinet_model.py` | 2× training data with Gaussian noise; Platt calibration uses original data only to prevent calibration bias |
| **P1-E** | Purged Embargo CV | `training_dataset.py` | Removes 5-day label-window overlap between train/test folds; adds 9 days of purge beyond the existing 14-day gap |
| **P2-A** | Sector Peer-Mean | `feature_generator.py` | Per-date sector-group mean of momentum/RSI/vol across ≤10 peers; O(n) first-pass loop; approximates graph neural net |

### Feature Breakdown (71 total registered)

```
Price & Returns       ~18 features   momentum_Nd, return_Nd, gap_pct, overnight_gap
Volume               ~12 features   volume_ratio, obv_slope, vwap_dev, force_index
Volatility           ~11 features   rolling_vol_Nd, atr_14, bbands_width, parkinson_vol
Trend                ~12 features   sma_cross, adx_14, rsi_14, macd_signal, ema_ratio
Market / Cross-sect. ~12 features   beta_21d, sector_return_5d, peer_rank_return_21d,
                                    sector_rank, regime_score
FII/DII Flows         6 features    fii_net_1d, fii_net_5d, fii_net_20d, dii_net_1d,
                      (P1-A new)    fii_dii_ratio, institutional_flow_signal
Sector Peer-Mean      3 features    peer_mean_momentum_10d, peer_mean_rsi_14,
                      (P2-A new)    peer_mean_vol_21d
```

---

## Dataset & Training Evidence

These are real numbers from the live DB and codebase — not projected or estimated.

| Metric | Value |
|---|---|
| Price rows in DB | 820k+ (5-year history) |
| Symbols tracked | 639 active (from 779 universe) |
| Feature rows generated | 13.8M+ |
| DB size on disk | ~97 MB |
| Walk-forward CV | Expanding window, 14-day gap + 5-day purge |
| Training speed (Ryzen AI 7 350) | ~1.5 min per full retrain |
| Algo population | 927 |
| Algos currently promoted | **0** (correct — re-earning edge under honest gates) |
| Gate source of truth | `backend/strategies/promotion_config.py` |

---

## Daily Automated Pipeline

Triggered at 15:30 IST weekdays by APScheduler. Can also be run manually:
`POST /admin/intelligence`

```
Step 01  Ingest prices        yfinance → price_data table
Step 02  Ingest news          RSS feeds → articles table
Step 03  Score sentiment      NLP → sentiment_scores table
Step 04  Update breadth       FII/DII + market breadth tables
Step 05  Build features       71-feature vectors → features_v2 table
Step 06  Run ML predictions   AQRTINet v4.0 + ensemble → predictions table
Step 07  Execute paper trades Best algo + confidence threshold → paper_trades
Step 08  Evolve algos         Genetic algorithm: 11 families, 9 mutation ops
Step 09  Score failures       Track what went wrong → lessons table
Step 10  Update knowledge     Knowledge score recalculated
Step 11  Run research agents  7 agents + CRO daily brief
Step 12  Archive vault        Full snapshot → vault table + backup
```

---

## Architecture

```
Project AQRTI/
│
├── ui/
│   ├── index.html          ← Single-page shell: all 14 page sections
│   ├── style.css           ← Terminal design system (CSS custom properties)
│   ├── app.js              ← Navigation, charts, live hydration per page
│   └── api.js              ← All backend calls → localhost:8000/api/v1
│
├── backend/
│   ├── main.py             ← FastAPI entry point + APScheduler
│   ├── aqrti/
│   │   ├── api/routes/     ← 59 route files; full list at /docs
│   │   ├── database/       ← 93-table SQLAlchemy models + SQLite WAL
│   │   └── data/           ← Market data fetchers
│   ├── ml/
│   │   ├── models/         ← AQRTINet v4.0, CatBoost, NGBoost wrappers
│   │   ├── datasets/       ← Walk-forward folds, label generator (triple-barrier)
│   │   └── model_retrainer.py  ← Drift detection + rolling IC trigger
│   ├── features/
│   │   ├── feature_registry.py   ← 71 FeatureDef entries (source of truth)
│   │   ├── feature_generator.py  ← Batch + incremental generation; peer-mean
│   │   └── fii_features.py       ← FII/DII flow feature module (P1-A)
│   ├── strategies/
│   │   ├── strategy_lifecycle.py ← Promotion/retirement/quarantine state machine
│   │   ├── promotion_config.py   ← ALL gate constants (single source of truth)
│   │   └── strategy_generator.py ← Genetic algorithm engine
│   ├── paper_trading/      ← Paper engine, execution, position tracking
│   ├── agents/             ← 7 research agents + CRO brief generator
│   ├── sentiment/          ← News NLP, sentiment scoring, velocity
│   ├── learning/           ← Failure analysis, lessons, knowledge scoring
│   ├── vault/              ← Snapshot archive, date replay
│   └── data_supremacy/     ← FII/DII, breadth, sector rotation, options
│
└── plans/                  ← Design docs, changelog, diary, this README
```

### UI Layer (Vanilla JS — no framework)

```
index.html   Structure      Semantic HTML, all 14 sections
style.css    Presentation   CSS custom properties — full theme in :root {}
app.js       Logic
             ├── ChartRegistry     Owns all Chart.js instances; prevents canvas reuse errors
             ├── Page Renderers    One function per page, fully independent
             ├── Hydration Layer   Async fetchers called on every page visit
             │                    No mock/fallback data — empty states render explicitly
             └── Navigation        Re-hydrates on every visit (no stale cache)
api.js       API Layer      apiFetch/apiPost → localhost:8000/api/v1
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Vanilla HTML5 + CSS3 + ES2022 — no framework, by design |
| Charts | Chart.js 4.4 |
| API | Python 3.11 · FastAPI · Uvicorn |
| Database | SQLite (WAL mode) · SQLAlchemy ORM · 93 tables · ~97 MB |
| ML — prediction | AQRTINet v4.0 (custom) · CatBoost · NGBoost · scikit-learn |
| ML — features | 71 registered features · 13.8M+ rows generated |
| Data | yfinance · feedparser (RSS) · httpx |
| Scheduler | APScheduler (cron-based daily pipeline) |

---

## 14 Dashboard Pages

| # | Page | What It Shows |
|---|---|---|
| 1 | **Overview** | Portfolio value, daily P&L, regime, top predictions, equity curve |
| 2 | **Market Intelligence** | NIFTY/BANKNIFTY, breadth, sector strength, top movers |
| 3 | **Opportunity Rankings** | All predictions ranked by confidence + expected return |
| 4 | **News Intelligence** | High-impact events, sentiment trend, full news feed |
| 5 | **Sentiment Center** | Company + sector sentiment, velocity, fear/greed |
| 6 | **Algo Lab** | Leaderboard, evolution tree, regime affinity, graveyard, replay |
| 7 | **Model Center** | ML model registry, accuracy, calibration curve, walk-forward |
| 8 | **Learning Center** | Knowledge score, failures, lessons, drift, feature intelligence |
| 9 | **Research Ops** | 7 research agents, daily brief, agent health, pipeline status |
| 10 | **Paper Trading** | Open positions, equity curve, trade history, analytics |
| 11 | **Risk Center** | Exposure, VaR, drawdown, sector limits, circuit breakers |
| 12 | **Intelligence Vault** | Date replay — exactly what AQRTI knew + held on any past date |
| 13 | **Intelligence Lab** | Regime datasets, meta-learning, feature proposals, model memory |
| 14 | **Data Intelligence** | FII/DII flows, options PCR, breadth, earnings calendar |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# .venv/bin/activate            # Linux/Mac
pip install -r requirements.txt
python main.py
# → http://localhost:8000  |  Swagger: /docs  |  Health: /health
```

On first boot the 10-step catch-up pipeline runs — this can take a few minutes.
`AQRTI_LITE_MODE=1` skips heavy ML loops (RAM: ~800 MB → ~230 MB).

### Frontend

```bash
npm run dev
# → http://localhost:3000
```

### Useful API Calls

```
GET  /api/v1/overview           Portfolio value, regime, KPIs
GET  /api/v1/market             NIFTY, BANKNIFTY, sector strength
GET  /api/v1/predictions        Ranked prediction signals
GET  /api/v1/strategies         Algo leaderboard + fitness scores
GET  /api/v1/models             ML model registry
GET  /api/v1/risk               VaR, drawdown, circuit breakers
GET  /api/v1/paper-portfolio    Paper trading state
GET  /api/v1/replay/{date}      Vault date replay

POST /api/v1/admin/intelligence Full 12-step pipeline (manual trigger)
POST /api/v1/admin/train        Model retrain only
POST /api/v1/admin/predict      Prediction pipeline only
POST /api/v1/admin/paper-trade  Paper trade execution only
```

Full endpoint list: `http://localhost:8000/docs`

---

## Key Metrics to Watch

| Metric | Target | Warning |
|---|---|---|
| Intelligence Score | 70+ | < 60: predictions unreliable |
| Model Direction Accuracy | 65%+ | < 60%: use caution |
| Paper Win Rate | 55%+ | < 45%: algo failing |
| Sharpe Ratio | 1.0+ | < 0.5: poor risk-adjusted return |
| Max Drawdown | < 10% | > 15%: circuit breakers at risk |
| Data Quality Score | 80%+ | < 70%: predictions less reliable |

### Circuit Breakers (auto-pause paper trading)

| Trigger | Limit |
|---|---|
| Daily loss | −3% of portfolio |
| Weekly loss | −6% of portfolio |
| Monthly loss | −12% of portfolio |

---

## Research Agents

| Agent | Role |
|---|---|
| Market Research | Macro conditions, breadth, regime analysis |
| Pattern Research | Recurring price patterns across NSE universe |
| Algo Research | Discovers and tests new trading algos |
| Model Research | ML model performance, drift, calibration |
| News Research | Reads and scores news for market impact |
| Risk Research | Portfolio concentration, tail risk |
| CRO (Chief Research Officer) | Synthesises everything → Daily Intelligence Brief |

---

## Hard Rules (Non-Negotiable)

1. **No placeholder data — anywhere, ever.** If a data source is unavailable, the UI shows `NO DATA — source unavailable`. An honest gap beats a plausible lie.
2. **Honest metrics only.** No loosened gates, no capped costs, no look-ahead. If a metric looks too good (AUC ≈ 1.0, Sharpe > 3), treat it as a bug until proven otherwise.
3. **Verify, don't assume.** After any fix: check the DB, hit the endpoint, read the log.

---

## Glossary

| Term | Meaning |
|---|---|
| AUC | Area Under Curve — 0.5 = random, 1.0 = perfect prediction |
| Drawdown | Drop from portfolio peak to trough |
| ECE | Expected Calibration Error — gap between stated confidence and actual accuracy |
| FII/DII | Foreign / Domestic Institutional Investors |
| Fitness Score | AQRTI's combined algo rating across return, Sharpe, and drawdown |
| PCR | Put-Call Ratio — >1.2 bearish signal, <0.8 bullish |
| Regime | Market condition: BULL, BEAR, SIDEWAYS, VOLATILE, RECOVERY |
| Sharpe Ratio | Return per unit of risk (>1.0 good, >2.0 excellent) |
| Triple-Barrier | Label method: price hits TP, SL, or time limit — whichever first |
| VaR | Value at Risk — worst expected daily loss at 95% confidence |
| Walk-Forward | Train on past, validate on unseen future — the only honest backtest |

---

## Disclaimer

AQRTI is a research and paper-trading tool. It does not execute real trades or manage real money. Nothing in this system constitutes financial advice. Past paper-trading performance does not guarantee future results.

---

*NSE/BSE · FastAPI · SQLite · AQRTINet v4.0 · CatBoost · NGBoost · Chart.js · July 2026*

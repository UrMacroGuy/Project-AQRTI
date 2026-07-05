# PROJECT AQRTI — State as of 2026-06-25 (historical)

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).

## Intelligence Terminal: Architecture, Component Map & System Status

Version: 3.0 — Post Phase 8 (Strategy Engine Overhaul + Agent System)
Last Updated: 2026-06-25

---

## CURRENT STATUS

All phases through Phase 8 are complete and running. The system is live with:

- **4,087 strategies** in the population (momentum, mean_reversion, breakout, hybrid, regime_adaptive, sentiment_driven, volatility_play, volume_surge)
- **847 promoted strategies** across all 8 families, fitness scores 15–67
- **7 research agents** at 100% success rate, running daily pipeline
- **227 days of historical market regime data** backfilled (BULL/BEAR/SIDEWAYS/VOLATILE)
- **5-minute strategy backtest loop** running autonomously, clearing ~100 unscored strategies per cycle
- **Paper trading** active with open positions, full trade history
- **Intelligence Score: 71.5**, regime: SIDEWAYS

---

## FOLDER STRUCTURE

```
Project AQRTI/
├── ui/
│   ├── index.html          ← Single-page shell: 14 page sections
│   ├── style.css           ← Terminal design system (CSS custom properties)
│   ├── app.js              ← Navigation, charts, live hydration (all 14 pages)
│   └── api.js              ← API layer — all calls to FastAPI backend
│
├── backend/
│   ├── main.py             ← FastAPI entry point (port 8000)
│   ├── aqrti/
│   │   ├── api/routes/     ← 50+ REST API endpoints
│   │   ├── database/       ← SQLAlchemy models + SQLite (aqrti.db, WAL mode)
│   │   └── data/scheduler.py ← APScheduler: daily pipeline + 5-min strategy loop
│   ├── ml/                 ← CatBoost + LightGBM + XGBoost ensemble
│   ├── strategies/         ← Genetic algorithm strategy engine
│   │   ├── strategy_generator.py    ← 8-family DSL generator
│   │   ├── strategy_backtester.py   ← Signal-driven 365-day backtest
│   │   ├── fitness_engine.py        ← 5-dimension composite scoring
│   │   ├── evolution_engine.py      ← Tournament selection, crossover
│   │   ├── mutation_engine.py       ← 11 mutation ops including confidence_adjust
│   │   ├── strategy_lifecycle.py    ← candidate → shadow → promoted → retired
│   │   └── strategy_research_loop.py ← Family-balanced backtest allocation
│   ├── agents/             ← 7 research agents + CRO + daily brief
│   ├── paper_trading/      ← Paper engine, execution, performance tracking
│   ├── learning/           ← Failure analysis, lessons, knowledge scoring
│   ├── intelligence_training/ ← Regime datasets, meta-learning
│   ├── data_supremacy/     ← FII/DII, options PCR, breadth, sector rotation
│   ├── vault/              ← Snapshot archiving, date replay, backup
│   ├── sentiment/          ← News NLP, sentiment scoring, velocity
│   ├── news/               ← RSS ingestion + article processing
│   └── features/           ← Feature store, 148 features per stock
│
├── plans/                  ← Architecture docs (this folder)
├── AQRTI_USER_GUIDE.md     ← Plain-English user guide
├── CHANGELOG.md            ← Session-by-session change log
└── package.json            ← npm scripts: dev server + backend launcher
```

---

## THREE-LAYER UI ARCHITECTURE

```
index.html   →  Structure Layer      (14 page sections, semantic HTML)
style.css    →  Presentation Layer   (CSS tokens, swap theme in :root {})
app.js       →  Logic Layer
               ├── DataStore         → Fallback mock data (mirrors API schemas)
               ├── ChartRegistry     → Owns all Chart.js instances, prevents canvas errors
               ├── Page Renderers    → One hydration function per page
               ├── Hydration Layer   → Async live-data fetchers called on page visit
               └── Navigation        → Re-hydrates on every visit
api.js       →  API Layer            → apiFetch / apiPost → localhost:8000/api/v1
```

---

## STRATEGY ENGINE ARCHITECTURE

### Fitness Engine (5 Dimensions)
| Dimension | Weight | What It Measures |
|---|---|---|
| Profitability | 30% | Sharpe (cap 3.0), profit factor (cap 4.0), total return |
| Consistency | 25% | Win rate vs 55% target, expectancy |
| Robustness | 20% | Works across multiple regimes, drawdown penalty |
| Regime Adaptability | 15% | Performs in current regime (SIDEWAYS) |
| Longevity | 10% | Trade count ≥ 8 to qualify, full credit at 30+ |

### Strategy Lifecycle States
```
candidate → [backtest] → shadow → [fitness ≥ 20 + trades ≥ 8] → promoted → [human approve] → active
                                    [fitness < 8] → retired → graveyard
```

### Backtest Engine
- 365-day historical window using real price data
- ML predictions (primary signal) + RSI+EMA fallback
- Per-day regime lookup from `MarketRegime` table (227 days backfilled)
- Family-balanced allocation: each of 8 families gets proportional batch slots
- Runs every 5 minutes via APScheduler (100 strategies per cycle)

---

## AGENT SYSTEM

| Agent | Last Run | Status | Findings |
|---|---|---|---|
| CRO (Chief Research Officer) | 2026-06-25 | ✅ success | 2 (aggregated brief) |
| Market Research | 2026-06-25 | ✅ success | 4 |
| Model Research | 2026-06-25 | ✅ success | 6 (2 high-urgency) |
| News Research | 2026-06-25 | ✅ success | 3 (high-urgency detected) |
| Pattern Research | 2026-06-25 | ✅ success | 6 |
| Risk Research | 2026-06-25 | ✅ success | 4 |
| Strategy Research | 2026-06-25 | ✅ success | 8 |

All agents run via `POST /api/v1/agents/admin/run-pipeline` or automatically in the daily scheduler (Step 9).

---

## CURRENT STRATEGY POPULATION (2026-06-25)

| Family | Total | Backtested | Best Fitness | Avg Sharpe |
|---|---|---|---|---|
| momentum | 877 | 530 (60%) | 60.6 | −3.6 |
| regime_adaptive | 483 | 74 (15%) | 42.1 | −2.0 |
| hybrid | 475 | 100 (21%) | 46.3 | −1.7 |
| volatility_play | 507 | 10 (2%) | 67.3 | — |
| sentiment_driven | 449 | 101 (22%) | 32.8 | −2.4 |
| breakout | 446 | 111 (25%) | 25.7 | −5.9 |
| mean_reversion | 429 | 103 (24%) | 38.4 | −1.5 |
| volume_surge | 421 | 93 (22%) | 57.0 | −11.2 |

~3,000 unscored candidates remain. The 5-minute scheduler loop clears ~100/cycle.

---

## ADMIN ENDPOINTS (KEY)

| Endpoint | Method | What It Does |
|---|---|---|
| `/api/v1/strategies/admin/bulk-backtest?batch_size=N` | POST | Backtest N unscored strategies (background, instant return) |
| `/api/v1/strategies/admin/rescore` | POST | Recompute all fitness scores + lifecycle sweep |
| `/api/v1/strategies/admin/full-research-cycle` | POST | generate + backtest + rescore + lifecycle + evolve (background) |
| `/api/v1/strategies/admin/generate?n=N` | POST | Generate N new candidate strategies |
| `/api/v1/strategies/admin/evolve?n_offspring=N` | POST | Evolve N offspring via tournament selection |
| `/api/v1/agents/admin/run-pipeline` | POST | Run all 7 agents + CRO |
| `/api/v1/agents/admin/register-all` | POST | Register all agents in DB |
| `POST /admin/intelligence` | POST | Full 12-step daily pipeline |

---

## KNOWN ISSUES / BACKLOG

- ML model outputs mostly Bearish/Neutral with negative `expectedReturn` — paper trading uses `abs(expectedReturn)` as workaround; real fix requires model retrain
- `volatility_play` backtest coverage still low (2%) — scheduler will clear over time
- Options Intelligence shows `status: no_data` — scraper not run
- Learning/Knowledge tab lessons populate only when paper positions close (all 4 currently open)

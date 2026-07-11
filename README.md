# AQRTI

Research-driven quant engine for a curated real-money-adjacent Indian equity portfolio (NSE), built around actual research — corporate filings, earnings, news, LLM-synthesized theses — rather than random strategy mutation.

**Status:** personal project, active development. AQRTI suggests; the user decides — there is no broker write API anywhere in the codebase, by design.

## Overview

AQRTI tracks a fixed curated universe (9 NSE symbols + VOO/QQQ monitor-only + NIFTY 50 benchmark/regime) rather than a broad market screen. Its daily pipeline scrapes real corporate filings/earnings/news, synthesizes them via LLM into a cited research thesis per symbol (every conclusion traceable to a real source row — fabricated citations are rejected before ever reaching the database), and generates candidate algos from six named, academically-grounded quant templates (post-earnings drift, momentum, mean-reversion, event-catalyst, regime-conditioned DCA timing, cross-sectional rotation). Every algo must clear an honest backtest, an out-of-sample holdout, a benchmark-vs-buy-and-hold gate, a duplicate-detection gate, 12-fold walk-forward validation, and a ≥60-day forward-paper quarantine before a human ever gets to approve it — and even then, it never trades automatically. AQRTI surfaces suggestions; the user reviews and executes every trade manually.

## Stack

Python (FastAPI, SQLAlchemy) · SQLite (WAL) · vanilla JS + Chart.js frontend · LLM research synthesis via OpenRouter/NVIDIA NIM.

## Running locally

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # fill in your own free-tier API keys
python main.py          # http://localhost:8000, docs at /docs

npm run dev              # http://localhost:3000
```

## Documentation

`plans/CHANGELOG.md` — session history, newest first, start here for the latest state. `docs/RESEARCH_DRIVEN_REARCHITECTURE.md` — full current architecture reference. `docs/MARKOV_STRATEGY_PLAN.md` — the isolated Markov/HMM regime module.

## Disclaimer

Research and suggestion engine only. No real-money execution, no broker integration, no auto-trading. Nothing here constitutes financial advice — the user makes every trade decision manually.

# AQRTI

Self-learning quant research and paper-trading platform for Indian equity markets (NSE/BSE).

**Status:** private, internal development. Not for public distribution.

## Overview

AQRTI runs an autonomous daily research pipeline — market data ingestion, feature engineering, ML-based prediction, strategy evolution, and paper-trade simulation — surfaced through a 14-page browser dashboard. It does not place real trades; every position is virtual.

The ML core, **AQRTINet**, is maintained separately as a public, source-available project: [github.com/UrMacroGuy/aqrtinet](https://github.com/UrMacroGuy/aqrtinet).

## Stack

Python (FastAPI, SQLAlchemy) · SQLite (WAL) · scikit-learn / CatBoost / NGBoost · vanilla JS + Chart.js frontend.

## Running locally

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python main.py          # http://localhost:8000, docs at /docs

npm run dev              # http://localhost:3000
```

## Documentation

Session history, architecture, schema, and roadmap docs live under `plans/` and `docs/`. Start with `plans/CHANGELOG.md` for the latest state.

## Disclaimer

Research and simulation only. No real-money execution. Nothing here constitutes financial advice.

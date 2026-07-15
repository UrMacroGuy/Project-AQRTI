<div align="center">

# AQRTI — Intelligence Terminal

**A research-driven quant strategy engine for a hand-picked, real-money NSE portfolio.**

Scrapes real filings, earnings, and news → synthesizes cited research with an LLM → generates algos from academically-grounded templates → validates them through brutal, honest gates.

*AQRTI suggests. The human decides. It never places a trade.*

![Python](https://img.shields.io/badge/Python-FastAPI%20%2B%20SQLAlchemy-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![Frontend](https://img.shields.io/badge/UI-Vanilla%20JS%20%2B%20Chart.js-F7DF1E?logo=javascript&logoColor=black)
![LLM](https://img.shields.io/badge/LLM-NVIDIA%20NIM%20%2F%20OpenRouter-76B900?logo=nvidia&logoColor=white)
![Tests](https://img.shields.io/badge/tests-121%20passing-brightgreen)
![License](https://img.shields.io/badge/use-personal%20research-lightgrey)

</div>

---

## Why this exists

Most retail "algo trading" projects mutate random indicator combinations against price history until something backtests well — then lose money live. AQRTI is built on the opposite premise: **strategies must be grounded in real research and proven effects, and every metric must survive honest validation before anyone acts on it.** When nothing passes the gates, the correct output is *zero signals* — the bar never moves to make results look better.

The project's own history proves the point: its strategy lab recently pre-registered a pullback system showing a 74.5% win rate in-sample, then watched it **fail out-of-sample** (-0.71%/trade) — and published that negative result instead of tuning until it passed ([docs/STRATEGY_LAB.md](docs/STRATEGY_LAB.md)).

## The universe

A fixed, curated 12-instrument portfolio — not a market-wide screen:

| Tier | Instruments | Role |
|---|---|---|
| **Owned** | BEL · HDFCBANK · NTPC | Monthly SIP accumulation; algos generate actionable signals |
| **Bench** | ICICIBANK · INFY · CDSL · DRREDDY · LT · HAL | Monitored for research-backed rotation suggestions |
| **US (monitor)** | VOO · QQQ | Fractional monthly buys; price-tracked only |
| **Benchmark** | NIFTY 50 | Regime detection + the bar every algo must beat |

## How it works

```
  NSE filings ─┐
  Earnings ────┤   ┌─────────────┐   ┌──────────────────┐   ┌─────────────────┐
  News RSS ────┼──▶│ LLM synthesis│──▶│ Strategy templates│──▶│ Honest gates     │
  FII/DII ─────┘   │ (cited, or   │   │ (PEAD, momentum,  │   │ OOS · ≥50% WR ·  │
                   │  rejected)   │   │  pullback, events,│   │ 0.8×NIFTY · WFO ·│
  Price history ──▶│              │   │  regime DCA,      │   │ 60d quarantine   │
  Markov regimes ─▶└─────────────┘   │  rotation)        │   └────────┬────────┘
                                      └──────────────────┘            ▼
                                                              Suggestions only —
                                                              human executes
```

1. **Collect** — free official/public sources only: NSE corporate filings, quarterly results, FII/DII flows, financial news RSS (MoneyControl, ET, LiveMint, Business Standard).
2. **Synthesize** — a free-tier hosted LLM turns each day's events into a structured research note (sentiment, catalysts, risk flags). Every conclusion must cite real source event IDs; fabricated citations are rejected before they touch the database.
3. **Generate** — algos come from **22 named templates** backed by published research (post-earnings drift, momentum, quality mean-reversion, event catalysts, regime-timed DCA, cross-sectional rotation, 52-week-high breakout, dual momentum, FII flow, ADX trend, delivery accumulation, and more) — never from random mutation. Thresholds are sampled from real measured feature distributions, not guessed ranges. An optional LLM touchpoint proposes parameterizations and reviews graveyard failures, but every proposal is validated against the live feature registry and real data before it can influence generation — a hint that fails validation is silently discarded, never coerced. Evolution tunes parameters *within* templates.
4. **Validate** — out-of-sample holdout, a hard ≥50% win-rate floor net of 0.28% NSE round-trip costs, a 0.8× NIFTY buy-and-hold Sharpe gate, duplicate detection, 12-fold walk-forward, then ≥60 days of forward-paper quarantine with ≥20 closed trades. Current honest status: the delivery-accumulation template (`accumulation_momentum`) is the first to clear the walk-forward bar (Sharpe 1.05); nothing has cleared full quarantine to `active` yet — most templates are still zero-trade or below the WFO bar, reported honestly rather than massaged.
5. **Monitor** — promoted algos are audited daily; win-rate decay, drawdown breach, or an unvalidated regime shift auto-demotes them. A monthly allocator ranks live signals for the SIP budget; paper-vs-real reconciliation flags any gap between simulated and actual fills.

## The dashboard

A terminal-style web UI (vanilla JS, no frameworks) with a strict no-mock-data rule — every number traces to a real database row from a real source, or the panel says `NO DATA — source unavailable`.

**Portfolio Cockpit** (all 12 instruments, live prices, research snippets, signals, SIP tilt) · **Research** (per-symbol news + filings + LLM synthesis with cited sources) · **Algos / Arena / Go-No-Go** (the promotion pipeline and a morning "what should I do today" verdict) · **Markov Regime** (Bull/Bear/Sideways transition matrix + HMM) · **Paper Portfolio · Risk Center**

## Quickstart

```bash
# Backend (Python 3.11+)
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
cp .env.example .env      # add your own free-tier API keys
python main.py            # http://localhost:8000 — Swagger at /docs

# Frontend
npm run dev               # http://localhost:3000
```

On boot the backend runs a self-healing catch-up pipeline (prices → filings → news → synthesis → features → regimes) and schedules the daily 15:30 IST cron automatically.

## Documentation

| Doc | What's in it |
|---|---|
| [plans/CHANGELOG.md](plans/CHANGELOG.md) | Session-by-session history with verification evidence — start here |
| [docs/RESEARCH_DRIVEN_REARCHITECTURE.md](docs/RESEARCH_DRIVEN_REARCHITECTURE.md) | Full architecture reference and design rationale |
| [docs/STRATEGY_LAB.md](docs/STRATEGY_LAB.md) | A complete honest R&D cycle — including the OOS failure |
| [docs/MARKOV_STRATEGY_PLAN.md](docs/MARKOV_STRATEGY_PLAN.md) | The Markov/HMM regime module |

## Principles (non-negotiable)

- **No fabricated data, ever.** An honest gap beats a plausible lie.
- **No gate-weakening.** If a metric looks too good (Sharpe > 3, AUC ≈ 1.0), it's treated as a bug until proven otherwise.
- **Point-in-time correctness.** A feature for date *d* may only read data known on date *d*.
- **Negative results get published.** Failed strategies are documented, not deleted.
- **The human is the last gate.** No broker write API exists anywhere in this codebase, by design.

## Disclaimer

Personal research software. Nothing in this repository is financial advice; all outputs are data-backed suggestions that the owner reviews and acts on manually, at their own risk. Past backtest performance — even honestly validated — does not guarantee future results.

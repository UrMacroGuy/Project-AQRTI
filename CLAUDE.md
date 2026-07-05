# CLAUDE.md — AQRTI Project Instructions

AQRTI is a self-learning quant research & paper-trading platform for Indian markets (NSE/BSE). It must be **realistic, data-backed, and proven — never lucky**. It suggests; the user reviews and trades manually. No real-money execution, ever.

## Hard rules (non-negotiable)

1. **No placeholder, mock, or fabricated data — anywhere, ever.**
   - Never seed DB tables with invented/estimated/random values (see the `seed_missing_data.py` incident, IMPROVEMENTS.md P0-1). If a data source is unavailable, the UI shows an explicit "NO DATA — source unavailable" state. An honest gap beats a plausible lie.
   - Never add mock/fallback objects to the UI that render when an API fails (`MOCK_*` patterns are banned). Every visible number must trace to a real DB row from a real source.
   - Synthetic/derived data is allowed **only** if flagged in the schema (e.g. `is_synthetic=True` on index-futures cost-of-carry rows) AND labeled wherever displayed, so it cannot be mistaken for real market data.
2. **Honest metrics only.** Never loosen a gate, cap, or cost model to make results look better. No look-ahead: no ML predictions in backtests, DSL evaluation is fail-closed (missing features → no entry), NSE costs 0.28% round-trip, mark-to-market daily Sharpe. If a metric looks too good (AUC ≈ 1.0, Sharpe > 3), treat it as a bug until proven otherwise — that instinct has caught two catastrophic bugs already.
3. **Verify, don't assume.** After any fix: check the DB, hit the endpoint, read the log. CHANGELOG entries record verified reality, including failures and limitations (see the `2026-07-03f` "data source reality check" entry for the standard).

## Terminology

Call the evolved trading strategies **"algos"** in all user-facing text, docs, and conversation. Keep "strategy" only in literal code identifiers (`StrategyV2`, `strategies_v2`, `strategy_lifecycle.py`).

## Sources of truth (when docs disagree, higher wins)

1. The code — especially `backend/strategies/promotion_config.py` (ALL promotion/retirement/quarantine gates; never re-declare its constants elsewhere).
2. `CHANGELOG.md` — session history, newest first. **Read the top entries at session start to catch up.**
3. `PROJECT_DIARY.md` — full-system reference. `DATABASE_AND_TRAINING.md` — schema + training pipeline.
4. `docs/STRATEGY_ARENA.md` — arena engine reference (its constants can lag the config).
5. `plans/*.md` — **historical design docs (June 2026). Do not trust their numbers or architecture claims.**
6. `IMPROVEMENTS.md` — active backlog; work items from there, check them off with dates.

## Session bootstrap — where every new session collects its tasks

Run this sequence at the start of EVERY session, before doing anything else:

1. **`CHANGELOG.md` (top 2-3 entries)** — what happened most recently; other sessions may have worked since you last did (same-day entries get letters: `[YYYY-MM-DD]`, `b`, `c`…).
2. **`IMPROVEMENTS.md`** — the task queue. If the user hasn't given a specific task, work the highest-priority unchecked item (P0 placeholder-data items first, then P1 docs, P-PF portfolio build, P-ARCH architecture, P2/P3). Follow its "How to work this file" rules: verify with evidence, check off with date, changelog, diary sync.
3. **Active build specs** live in `docs/` — read the spec before touching its items: `PERSONAL_PORTFOLIO_PLAN.md` (My Portfolio module → P-PF items), `OBSIDIAN_INTEGRATION_PLAN.md` (vault exporter → P-OBS items).
4. Deeper context when needed: `PROJECT_DIARY.md` (whole system), `DATABASE_AND_TRAINING.md` (schema/ML).

## Session workflow

- **After completing a task:** add a CHANGELOG entry (newest-first, dated `[YYYY-MM-DD<letter>]`), then sync `PROJECT_DIARY.md` per its §16 rule (timeline row for new phases; edit sections in place when numbers/architecture change; bump its "Last synced" line). Update `DATABASE_AND_TRAINING.md` if schema or training pipeline changed. Check off finished `IMPROVEMENTS.md` items with `(done YYYY-MM-DD)`.
- New problems found mid-task go into `IMPROVEMENTS.md` as items — never fixed silently, never ignored.
- Another session may be working concurrently (this has happened). Before bulk DB writes or file rewrites, re-read the target; never clobber an entry you didn't write.

## Personal Portfolio module (real money — extra rules)

The user's real 60-40 investment plan (₹2,000/month, Zerodha + INDmoney) is tracked in the "My Portfolio" section (spec: `docs/PERSONAL_PORTFOLIO_PLAN.md`). Rules beyond the global ones:
- Tracker + advisor ONLY. No broker write APIs, no order placement, no auto-execution — the user records transactions manually.
- Real-money tables (`Portfolio*`) never mix with paper trading or the algo population. `PortfolioTransaction` is append-only (corrections = reversal rows) — it's a tax audit trail.
- Mutual funds are valued at prior-day AMFI NAV and the UI must say so; never present NAV as real-time. Instruments get added only after verification (exact ticker/scheme code) — never guessed.

## Running & operating

- **Backend:** `cd backend && .venv\Scripts\activate && python main.py` → port 8000, Swagger at `/docs`, health at `/health`. On boot it runs a 10-step catch-up pipeline (can take minutes).
- **UI:** `npm run dev` → port 3000. Vanilla JS + Chart.js, no frameworks — keep it that way.
- **Scheduler:** daily pipeline cron 15:30 IST weekdays; algo micro-loop every 5 min; agents hourly; integrity sweep Sat 10:00 IST. `AQRTI_LITE_MODE=1` disables the heavy loops (RAM 800MB+ → ~230MB).
- **Database:** `backend/aqrti.db` — SQLite WAL, several GB. Before any bulk mutation, back up first (convention: `aqrti.db.bak-YYYYMMDD`). Running manual scripts alongside the live backend can hit `database is locked` — expected contention, prefer stopping the backend for heavy writes.

## Code conventions

- All table models live in `backend/aqrti/database/models.py` (one file, 93 tables). New tables go there, following existing index/unique-constraint patterns.
- API routes under `backend/aqrti/api/routes/`, all mounted at `/api/v1`.
- UI: page renderers + hydration functions in `ui/app.js`; every backend call goes through `ui/api.js`. Hydration re-runs on every page visit.
- Features: register the name in `features/feature_registry.py`, compute in the matching category module (`price/volume/volatility/trend/market_features.py`). **Point-in-time correctness is mandatory** — a feature for date `d` may only read rows ≤ `d`.
- SQLAlchemy sessions: on any failed flush/commit, `db.rollback()` before the session is used again — a logged-but-not-rolled-back error poisons every subsequent caller (root cause of the 2026-07-03e backend crash).
- The index-futures segment is fully isolated from stocks: `StrategyV2.asset_class` discriminator, parallel tables, own backtester. Never let the two populations mix in arena, promotion, or evolution queries.

## The quant bar (what "done" means for algo/ML work)

- An algo is only trustworthy after passing ALL of: honest backtest gates (`promotion_config.py`), the OOS holdout, the benchmark gate (0.8× NIFTY buy-and-hold Sharpe), the duplicate gate, and forward-paper quarantine (≥60 days promoted, ≥20 closed shadow trades, ≥50% WR, positive P&L). Human approval is the last gate, never the first.
- Current honest baseline (2026-07-03): **0 promoted algos** out of a 927 population. That is correct behavior, not a bug — do not "fix" it by weakening gates.
- Backtester changes require a spot-check: re-run a known algo and confirm the honest Sharpe moves for the stated reason.

# Road to Real — The Money-Readiness Roadmap

*The master roadmap from today's state to real capital. This file organizes ALL remaining work — items live in `IMPROVEMENTS.md` (the task queue); this file puts them in the right ORDER with exit criteria per stage, and defines the new §P-GO items that were missing. When every stage's exit criteria are met, AQRTI is ready to trade real money.*

Created 2026-07-05. Companion specs: `PERSONAL_PORTFOLIO_PLAN.md`, `OBSIDIAN_INTEGRATION_PLAN.md`. Task queue: `IMPROVEMENTS.md`.

---

## The honest starting point (read this first)

As of 2026-07-03d: **927 algos in the population, 0 promoted.** Every algo has negative honest Sharpe. That is not a bug — it's what the fixed, honest backtester says about the current population. It means:

> **The binding constraint on making money is NOT missing features. It is that no algo has yet proven an edge.**

Features (UI, portfolio page, Obsidian, alerts) make the system *usable*; only the evolution engine grinding against honest gates — plus time in forward-testing — makes it *profitable*. This roadmap therefore has two parallel tracks: **Track E (edge)** — things that help an algo pass the gates legitimately; **Track O (operations)** — things that make the system reliable and usable enough to act on that edge when it appears. Neither track is allowed to shortcut the gates. `promotion_config.py` values are the constitution; weakening them to "reach real money faster" is the one forbidden move.

**What "ready to make money" concretely means (the Go/No-Go scorecard, GO-1):**
1. ≥1 algo promoted through ALL honest gates (fitness ≥50, ≥60 trades, WR ≥52%, Sharpe ≥0.5, OOS pass, benchmark 0.8× NIFTY, duplicate gate).
2. That algo completes quarantine: ≥60 days promoted + ≥20 closed shadow trades + ≥50% WR + positive net P&L, on data that didn't exist when it was born.
3. System uptime: pipeline has run ≥30 consecutive trading days without silent failure (watchdog green).
4. The human workflow exists: a morning decision screen tells the user exactly what/why/how-much, and the user has paper-executed that workflow manually for ≥2 weeks.
5. First real capital: **₹5,000 max** (per the original Phase-10 plan), sized so a total loss is a tuition fee, not a disaster. Scale only after 3 months of real fills reconciling with paper assumptions (GO-6).

---

## Stage 0 — Trust floor ✅ (mostly complete)

The non-negotiables that everything else stands on. Status: **largely done** — kept here so the exit criteria stay visible.

- [x] Honest backtester (mark-to-market Sharpe, intrabar SL/TP, fail-closed DSL, NSE costs, no ML look-ahead) — Trust Overhaul 2026-07-02
- [x] All fabricated data purged (incl. the P0-6 audit finds: randomized FII/DII backfill rows, hardcoded HTML alerts); mock UI fallbacks removed; no-placeholder rule in CLAUDE.md — P0-1..6 done 2026-07-05
- [x] Full 5yr feature coverage; leakage guards in dataset builder
- [x] Docs synced to code: diary through `2026-07-05g`, STRATEGY_ARENA constants, division-by-zero doc closed — P1-1..9 done 2026-07-05
- [x] ARCH-1 stray root `aqrti.db` archived (done 2026-07-05) · GO-12 MIN_CONFIDENCE=60 confirmed (done 2026-07-05)

**Exit criteria:** zero known fabricated/stale-critical data anywhere; docs agree with `promotion_config.py`. **Met as of 2026-07-05.**

## Stage 1 — Reliability: the system must run itself (Track O)

If the pipeline silently dies for a week, every downstream date-sensitive process (quarantine day-counts, shadow trades, drift detection) corrupts or stalls. Real money cannot sit on a system that needs manual babysitting.

- [x] **GO-2 — Watchdog + auto-restart.** (done 2026-07-05) `backend/scripts/watchdog.py` + Windows Scheduled Task via `setup_watchdog_task.ps1`; amber restart-pill in UI topbar.
- [x] **GO-3 — Silent-failure alarm.** (done 2026-07-05) 16:30 IST self-check; `SystemHealthCheck` table; red UI banner.
- [x] **GO-4 — Alert channel out of the dashboard.** (done 2026-07-05) Telegram bot via `backend/aqrti/alerts/telegram_alerts.py`.
- [x] ARCH-2 — 37-test suite in `backend/tests/test_core.py`, all passing (done 2026-07-05)
- [x] ARCH-7 — `busy_timeout=30000` on all connections (done 2026-07-05)
- [x] ARCH-9 — weekly `.backup` + integrity check scheduled Saturday 08:00 IST (done 2026-07-05)
- [x] ARCH-4 — split scheduler from API process (done 2026-07-05) `python -m aqrti.scheduler`, PID-file detection, graceful shutdown
- [x] ARCH-3 — migration convention (done 2026-07-05) numbered idempotent scripts + `schema_migrations` table, wired into `init_db()`

**Exit criteria:** 30 consecutive trading days of pipeline completion with zero manual intervention; one drill: kill the process mid-day and verify auto-recovery + alert. *(Items done; uptime clock starts now.)*

## Stage 2 — Edge: give evolution its best legitimate shot (Track E)

The population breeds 24/7. These items improve the *search*, never the *grading*:

- [x] **GO-5 — Population diagnosis report.** (done 2026-07-05) See `docs/GO5_POPULATION_DIAGNOSIS.md`. Verdict: win-rate collapse (median 47.1%), median Sharpe –2.1. Root cause: DSL conditions generate random-walk-frequency signals. GO-5b must fix signal quality.
- [x] **GO-5b — Search-space upgrades (informed by GO-5).** (done 2026-07-05) Added 3 families: `relative_strength` (cross-sectional nifty_rs_21d+sector_rs_21d, 20-45d), `breadth_momentum` (breadth_pct_above_ema50 filter, 15-35d), `long_hold_momentum` (delivery_pct+ema50, 30-60d, weight=0.14 highest). 5 new REGIME_FEATURES added.
- [x] **GO-5c — Walk-forward evolution honesty check.** (done 2026-07-05) `backend/scripts/go5c_oos_audit.py` — PASS WITH WARNINGS; 3.4% near-identical Sharpe (fine); OOS windows extend to ~2027-01-01 (no pristine holdout remains — deferred final audit until first promoted algo).
- [ ] P-PF-7 / index-futures segment maturation — more independent segments = more shots at an edge (futures have far lower round-trip costs than delivery equity, a structural advantage worth testing)
- [ ] ARCH-12 only if training-build time actually becomes the bottleneck

**Exit criteria:** either ≥1 algo legitimately promoted, or a written, evidence-backed conclusion about which search direction is next. (Time in market is a real input here — quarantine alone takes 60+ days. Start it early; everything else can proceed in parallel.)

## Stage 3 — The human workflow: from signal to action (UI track)

AQRTI suggests; the user executes. Today the UI is an *observatory* (14 pages of state). Money-making needs a *cockpit*:

- [ ] **GO-7 — Morning Decision Screen (new UI page or Overview overhaul).** One screen answering: *what should I do today and why?* — today's actionable signals (algo, symbol, direction, size ₹, SL/TP, confidence, the algo's live quarantine/paper record), current regime + risk posture, circuit-breaker state, and an explicit "NO ACTION TODAY" state when there's nothing (honest emptiness, not filler). Each signal has a one-tap "acted on it / skipped" record — building the compliance log that later reconciles paper vs real.
- [ ] **GO-8 — Quarantine progress board.** Per promoted algo: days-in-quarantine countdown, shadow trades accumulated, live WR vs the 50% bar, net P&L — so the user can see edge *being proven* rather than discovering it later.
- [ ] **GO-9 — UI truth-and-polish pass.** Every number gets timestamp+source on hover; every panel has a real empty/error state (audit all 14 pages); kill any remaining stale-cache renders; P3-5 algo-rename leftovers; ARCH-5 split app.js into per-page modules BEFORE adding the new pages (GO-7, PF-5).
- [ ] PF-1..PF-6 — My Portfolio module (the real-money tracker per its spec — this page is where real fills get recorded)
- [ ] ARCH-8 — bind 127.0.0.1 + token on mutation routes (before any remote/mobile access)
- [ ] Optional: mobile access via Obsidian vault (already exports to OneDrive) or LAN access after ARCH-8 — the decision screen matters most at 9:00 AM, not at the desk

**Exit criteria:** user runs the full morning ritual (decision screen → act/skip → record) for 2 weeks on paper signals without friction notes.

## Stage 4 — Real-money bridge (only after Stages 1-3 exit)

- [x] **GO-1 — Go/No-Go scorecard rendered live in the UI** (done 2026-07-05) `GET /api/v1/go-nogo` + `GET /go-nogo/uptime-log`; new "Go / No-Go" page in dashboard with 5-condition cards, quarantine board, actionable signals, 30-day uptime dot chart. All 5 conditions correctly red today (0 promoted algos).
- [ ] **GO-6 — Paper-vs-real reconciliation.** From the first real fill: record every real trade in the portfolio module, auto-compare fill price/costs/slippage vs the backtester's assumptions (0.28%, close-fills). If real costs exceed modeled by >20%, feed corrected costs back into the cost model and REGRADE the population — reality outranks the model.
- [ ] **GO-10 — Real-capital risk rails (process, not code):** start ₹5,000; one algo only; position sizing per the algo's DSL but capped ₹1,000/position; hard stop — if real drawdown hits −10%, halt, write post-mortem, return to paper. Documented in the decision screen so the rules are visible at decision time.
- [ ] **GO-11 — Monthly review ritual:** live vs backtest WR/expectancy per algo, cost reconciliation, lessons — one generated report (Obsidian note + UI), 30 minutes, monthly.

**Exit criteria:** 3 consecutive months where real results reconcile with paper within tolerance → earn the right to scale capital gradually (2× at most per quarter, never on a drawdown month).

## Stage 5 — Later / deliberately deferred

Broker read-API import (Zerodha Kite Connect costs ₹500-2k/mo — not before real capital justifies it) · options/derivatives algos · cloud hosting (DB too big for free tiers; local + watchdog is fine) · OBS-5 two-way Obsidian · ARCH-6/10/11 (models.py split, legacy table drops, Electron rebuild — opportunistic).

---

## Sequencing at a glance

```
  now ──► Stage 0 finish (docs sync, stray DB)          ~small
      ├─► Stage 1 reliability (GO-2,3,4 + ARCH 2/4/7/9) ──┐  runs forever after
      ├─► Stage 2 edge (GO-5 diagnosis first!)            │  60+ day quarantine clock
      │        └── evolution + quarantine keep running 24/7 ──► first promoted algo
      └─► Stage 3 cockpit (ARCH-5 → GO-7,8,9 → PF-1..6)   │
                                                           ▼
                              Stage 4: all-green scorecard → ₹5,000 → reconcile → scale
```

Rule of thumb for any session picking work: **Stage-0/1 items before Stage-3 polish; GO-5 before any new algo families; nothing from Stage 4 until Stages 1-3 exit criteria are literally met.** The queue in IMPROVEMENTS.md §P-GO mirrors the GO-items defined here.

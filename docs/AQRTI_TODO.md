# AQRTI — TODO
_Updated 2026-07-07 (night session). Source of truth for priorities: `plans/IMPROVEMENTS.md` + `docs/ROAD_TO_REAL.md`._

## What's done as of tonight
- **CatBoost is the only production model.** AQRTINet retired (source kept for
  reference, unused in production). No ensemble/multi-model blending.
- **Strategy Research Loop is fixed and running.** It generates/backtests/
  scores/evolves algos every 5 minutes as an isolated OS subprocess
  (`backend/scripts/strategy_loop_cycle.py`), not an in-process thread — it
  can no longer freeze the API/UI via GIL contention like it did earlier today.
- **CatBoost retraining is now gated on real new data**, not a clock or
  rolling-metric decay: needs ~1500+ new price rows since last training
  (~weekly cadence at current data volume) before it retrains, and trains on
  a 90-day rolling window (not full history) to stay fast and RAM-friendly.
- **Desktop launchers wired up:** "Start AQRTI" / "Stop AQRTI" shortcuts on
  the Desktop cleanly start/stop backend+frontend+strategy-loop, including
  orphaned duplicate processes (this machine sometimes spawns two Python
  interpreters for the same process — both get caught).
- **aqrtinet public repo README rewritten** — reframed as a research
  case-study (not "in production"), with an honest postmortem on the
  regime-routing bug and degenerate-threshold bug found during today's
  evaluation work.
- Committed and pushed to `Project-AQRTI` on GitHub. Fixed a `.gitignore` gap
  that would have let the live `aqrti.db` and stray log files get committed.

## The one number that matters most
**0 algos promoted out of 1224+ generated.** This is the real blocker to
trading — not model choice, not training cadence. An algo needs to clear
honest backtest gates (OOS holdout, benchmark vs 0.8x NIFTY buy-and-hold,
duplicate gate) and then survive ≥60 days of forward-paper quarantine with
≥20 closed trades and positive P&L before it's trustworthy enough to trade
for real. **Getting to your first trade is a "get algos to pass the gates"
problem.** The strategy loop running again (see above) is the prerequisite;
now it needs to actually run long enough, and produce good enough signal, to
clear those gates.

## Immediate priorities (in order)

- [ ] **Let the strategy loop run for a few days and check population health.**
      Snapshot taken 2026-07-07: 1224 algos, 0 promoted, matches this file's
      baseline. `relative_strength` has 22 rows but most are unbacktested
      (win_rate=0/None); `breadth_momentum` and `long_hold_momentum` have
      ZERO rows yet — the generator code exists but hasn't produced any
      candidates. Genuinely needs more wall-clock time; can't be forced to
      completion in one session. Check back in a few days as originally
      planned.

- [x] **ML prediction pipeline is slow — batch it.** (done 2026-07-07)
      Rewrote `ensemble_engine.predict_universe()` to build one multi-row
      DataFrame per model per task and call `predict_proba()`/`predict()`
      once across all symbols, instead of looping per-symbol. But the REAL
      dominant cost turned out to be pattern search, not model inference:
      `run_pattern_search()` rebuilt a full-market historical feature matrix
      (258k rows, ~92s) from scratch on EVERY symbol call — ~106 symbols ×
      92s ≈ 2.7 HOURS per prediction run. Fixed by building the matrix once
      per pipeline run and passing it through (`prebuilt_matrix` param).
      Full pipeline now completes in ~5-7 min instead of hours.

- [x] **Fix the sentiment/regime boot-step bug.** (done 2026-07-07) Root
      cause was the OPPOSITE of what a previous session's BUG_HUNTING.md
      entry (C9) claimed — that "fix" had the tz-naive/aware direction
      backwards and left the crash fully in place through this morning.
      `NewsEvent.timestamp` is always naive (explicitly stripped on insert
      in `news_pipeline.py`); the bug was `now` being tz-AWARE. Fixed:
      `now = datetime.utcnow()` in `company_sentiment.py`. Verified live —
      `run_sentiment_pipeline()` now completes clean.

- [x] **Run a full, honest CatBoost benchmark.** (done 2026-07-07) Blocked
      on a bigger bug first (see below) — full run: 352 symbols, 29,044 rows,
      accuracy 48.25%, AUC-ROC 0.485, hit_rate 48.25%. Near coin-flip,
      consistent with the 0/1224 promoted reality — not a new problem.

- [ ] **GO-6 — Paper-vs-real reconciliation** (not started, correctly —
      structurally blocked on "first real fill" which doesn't exist yet).

- [ ] **GO-9 — UI polish pass** (in progress). Not blocking trading.

## Critical bugs found + fixed this session (2026-07-07, day session)

While chasing the benchmark/batching items above, found the production
training path was **completely broken** — worth its own section since it's
bigger than what was originally scoped:

- **`DEFAULT_TRAINING_WINDOW_DAYS=90` collapsed training to 1 symbol.** The
  90-day window's comment claimed "clears MIN_ROWS_PER_SYMBOL=50 with
  margin" — never verified, and wrong: only ~48 rows/symbol actually survive
  end-to-end. `build_full_dataset()` was silently returning 1 symbol/50 rows
  instead of the full universe, with NO error (the all-fail guard only
  fires when literally every symbol fails). Raised to 150 days — verified
  352 symbols / 29,044 rows recovered, matching the documented "352
  backtest-eligible" universe count.
- **`run_full_training()` (the actual `/admin/train` entrypoint) skipped ALL
  3 tasks on every run, silently.** It required walk-forward folds, which
  need `WF_TRAIN_YEARS=1.0` (1 year) of history — impossible under the new
  90-150 day window. Zero models had been trained since this policy was
  introduced; the live model was stuck on a June 28 snapshot. Confirmed the
  stale model was degenerate: EVERY symbol got the identical
  direction_prob=0.5002/Neutral regardless of features. Fixed: skip only
  the walk-forward diagnostic step when folds=0, still train + register the
  model directly (matches what `compare_models.py` already did correctly).
- **Two more registry bugs surfaced retraining after the above fix:**
  artifact filenames collided between direction_5d and outperform_binary
  (both saved to the same .pkl, silently overwriting each other), and the
  model_versions table's own unique constraint + registration lookup didn't
  account for label_col, so outperform_binary's results were getting lost
  or erroring outright. Both fixed (new migration 0003 widens the
  constraint); also fixed old model versions (v57) staying is_active=True
  forever alongside fresh retrains, diluting the ensemble average with
  stale predictions.
- **End state, verified:** all 3 tasks (direction_5d, expected_return,
  outperform_binary) now train cleanly, save to distinct files, register
  distinct DB rows. Predictions are genuinely varied again (12 distinct
  confidence values, 7 distinct expected_return values, 4/106 symbols
  correctly Bullish) instead of 106/106 identical. Model quality is still
  weak (AUC ~0.485) — that's honest reality matching the 0/1224 promoted
  population, not something this session was expected to fix.

Full details + verification evidence for every bug: `plans/BUG_HUNTING.md`
(C9 correction, C12, C13, C14, C15) and `plans/CHANGELOG.md`.

## Housekeeping / smaller items
- [ ] Decide whether to delete unused AQRTINet source files
      (`backend/ml/models/aqrtinet_model.py`, `aqrtinet_percentile.py`) or
      keep for reference. No rush — nothing imports them in production.
- [x] **Duplicate Python processes — root cause found + fixed.** (done
      2026-07-07) Not a PATH/interpreter issue — `scripts/start_backend.bat`
      only killed port 8000 once, before its restart `:loop`. Launching it
      twice meant both copies kept independently respawning `python main.py`
      on their own 3s timers, fighting over the port forever. Added a lock
      file so a second launch exits cleanly instead of racing; `STOP
      AQRTI.bat` clears the lock so the next Start AQRTI works normally.
- [x] **Backend auto-shutdown / needs a real process supervisor.** (done
      2026-07-07) `docs/ROAD_TO_REAL.md` marked GO-2 (watchdog + auto-
      restart) done, but the Windows Scheduled Tasks it depends on were
      never actually registered on this machine — confirmed via
      `Get-ScheduledTask` returning nothing. The backend was only ever a
      plain child process of whatever terminal launched it. Ran
      `backend/scripts/setup_watchdog_task.ps1` elevated; `AQRTI Backend`,
      `AQRTI Watchdog`, `AQRTI Scheduler` are now registered (state: Ready) —
      start at login, auto-restart on crash/hang.

## Context for the "start trading soon" goal
Per `CLAUDE.md`'s hard rules: no real-money execution ever happens
automatically — algos are suggestions, you review and trade manually.
"Starting trading" means: get at least one algo through all the gates, see
it show up as a promoted "champion," then manually decide whether to act on
its live signal. Quarantine alone is 60 days minimum once an algo starts
passing gates — so the sooner the population produces gate-passing
candidates, the sooner that clock starts. That's the critical path, and it
runs on its own now every 5 minutes via the strategy loop — the main thing
left to do is let it run and watch what it produces.

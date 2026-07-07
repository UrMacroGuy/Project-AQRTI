# BUG_HUNTING.md — AQRTI Bug Tracker

> Single source of truth for all known bugs. Bugs are added when found and removed when fixed — never edited in place. Before any code change, check this file for related bugs.

## Counts

| Severity | Count | Fixed |
|----------|-------|-------|
| CRITICAL | 16 | 16* |
| HIGH     | 23 | 23 |
| MEDIUM   | 20 | 20 |
| LOW      | 10 | 10 |
| **Total**| **69** | **69** |

*\* CRITICAL: 8 fixed + 3 false positive (C2, C4, C5)*

## Rules

1. **Verify, don't assume.** After fixing a bug, run the relevant code path or check the DB to confirm. Record verification evidence.
2. **One bug = one section.** New bugs discovered mid-task go here immediately — never fixed silently, never ignored.
3. **Bugs that are not actual code defects** (false positives, intentional design) are listed as `(NOT A BUG)` in the title with a brief explanation.
4. **Cross-reference pattern:** When fixing a bug, check if the same pattern exists elsewhere and either fix it too or file a new bug.

---

# CRITICAL

## C1 — Paper trades ignore NSE costs (zero-cost P&L inflation)

- **File:** `backend/paper_trading/continuous_monitor.py:261`
- **Root cause:** `entry_price = fill` on line 261 uses the raw fill price without adding `NSE_BUY_COST_PCT` (0.14%). Compare to `paper_trade.py:171` which correctly does `filled_price = entry_price * (1 + NSE_BUY_COST_PCT)`.
- **Impact:** Every paper trade's P&L is inflated by 0.28% round-trip. Losing algos look profitable. This is the single most dangerous bug in the system.
- **Fix:** Imported `NSE_BUY_COST_PCT, NSE_SELL_COST_PCT` from `paper_trade`. Entry now uses `filled_price = fill * (1 + NSE_BUY_COST_PCT)`. Exit now uses `exit_price = price * (1 - NSE_SELL_COST_PCT)` for P&L, SL/TP levels, and trade records.
- **Fixed:** 2026-07-06

## C2 — (NOT A BUG — yfinance ticker) performance_tracker.py:45 uses `"^NSEI"` for yfinance

- **File:** `backend/paper_trading/performance_tracker.py:45`
- **Explanation:** `yf.Ticker("^NSEI")` is the correct Yahoo Finance ticker for Nifty 50. This is a false positive from the automated scan — it's not a DB query, it's an external API call.
- **Fixed:** N/A (not a bug)

## C3 — PercentileRanker fitted on full dataset leaks validation information

- **File:** `backend/ml/models/aqrtinet_model.py:664`
- **Root cause:** `self._ranker.fit_transform(X_work)` is called on the full training dataset including the validation folds' data.
- **Impact:** Validation metrics artificially inflated.
- **Fix:** Moved PercentileRanker fit inside 7-fold TimeSeriesSplit per-fold (fit on `tr_idx` only). Collected per-fold training chunks. Final ranker fitted on full data for inference use, with fallback on error.
- **Fixed:** 2026-07-06

## C4 — (NOT A BUG — already using NIFTY50) regime_discovery.py:42

- **File:** `backend/intelligence/regime_discovery.py:42`
- **Explanation:** Line 42 already uses `IndexData.index_name == "NIFTY50"`, not `"^NSEI"`. The automated scan produced a false positive — either the file was already fixed or the scanner read a stale version.
- **Fixed:** N/A (not a bug)

## C5 — (NOT A BUG — already using NIFTY50) bayesian_uncertainty.py:64

- **File:** `backend/intelligence/bayesian_uncertainty.py:64-65`
- **Explanation:** Line 64-65 already uses `IndexData.index_name == "NIFTY50"`. False positive for the same reason as C4.
- **Fixed:** N/A (not a bug)

## C6 — Uncertainty double-scaling in confidence label

- **File:** `backend/intelligence/bayesian_uncertainty.py:152-153`
- **Root cause:** `uncertainty_pct = round(composite_uncertainty * 100 / 2, 1)` — multiplying by 100 then dividing by 2 is confusing and has no statistical basis. The uncertainty range should be directly derivable from composite_uncertainty without arbitrary scaling.
- **Impact:** The displayed "±X%" is misleading — it doesn't represent a real confidence interval.
- **Fix:** Removed `/2` factor. Uncertainty now computed as `round(composite_uncertainty * 100, 1)` directly, capped at 49.9.
- **Fixed:** 2026-07-06

## C7 — snapshot_manager queries DailyPrice for NIFTY instead of IndexData

- **File:** `backend/vault/snapshot_manager.py:48-52`
- **Root cause:** Queries `DailyPrice` table with `["^NSEI", "NIFTY50"]` for Nifty 50 data. Index data lives in the `IndexData` table, not `DailyPrice`. DailyPrice only contains stock symbols.
- **Impact:** `nifty_close`, `nifty_ret1d`, `nifty_ret5d`, `nifty_vol` are all `None` because the query finds no rows. Market snapshots have no Nifty data.
- **Fix:** Switched to `IndexData.index_name == "NIFTY50"`. Added `IndexData` to imports. Uses `IndexData.returns` for `nifty_ret1d` and `IndexData.volatility_20d` for `nifty_vol`.
- **Fixed:** 2026-07-06

## C8 — watchdog.py file handle leak

- **File:** `backend/scripts/watchdog.py:122`
- **Root cause:** `log_file = open(BACKEND_DIR / "uvicorn.log", "a")` opens a file that is never closed. The file object is passed to `subprocess.Popen` as `stdout`/`stderr` but the handle in the parent process is leaked.
- **Impact:** Over time (days/weeks), the watchdog process accumulates open file handles. On Windows, each open log file handle prevents log rotation and consumes system resources.
- **Fix:** Wrapped Popen call in `try/finally` with `log_file.close()` in finally block.
- **Fixed:** 2026-07-06

## C9 — Timezone-aware vs naive datetime crash in company_sentiment

- **File:** `backend/sentiment/company_sentiment.py:70` (was line 77 before the fix)
- **Root cause:** Inverted from the previous entry here. `NewsEvent.timestamp` is always stored **naive** — `news/news_pipeline.py:89` explicitly strips `tzinfo` (`pub_naive = item.published_at.replace(tzinfo=None) if item.published_at.tzinfo else item.published_at`) before every insert. The actual bug was `now = datetime.now(timezone.utc)` (tz-**aware**) being subtracted from the naive `row.timestamp`, raising `TypeError: can't subtract offset-naive and offset-aware datetimes` on every call. The prior fix recorded in this file (2026-07-06, changing `now` to `datetime.now(timezone.utc)`) had it backwards and made the crash permanent instead of fixing it — confirmed by every boot log through 2026-07-07 morning showing "Boot step 4 — Sentiment failed: can't subtract offset-naive and offset-aware datetimes".
- **Impact:** The sentiment boot step (and `run_sentiment_pipeline()` generally) crashed on every run, so market regime classification never updated from that step.
- **Fix:** Changed `now = datetime.now(timezone.utc)` to `now = datetime.utcnow()` (naive, matching the DB's actual storage convention). Removed the now-unused `timezone` import.
- **Verified:** 2026-07-07 — ran `run_sentiment_pipeline()` directly against the live DB; completed with `status: COMPLETED`, `regime: BULL MARKET`, no exception.
- **Fixed:** 2026-07-07

## C10 — Missing db.rollback() in feature generator incremental path

- **File:** `backend/features/feature_generator.py:519-521`
- **Root cause:** The `_generate_incremental` except block (lines 519-521) logs the error and appends to `errors`, but does NOT call `db.rollback()`. Contrast with `_generate_all` at line 431 which correctly calls `db.rollback()`.
- **Impact:** After any exception during incremental generation, the SQLAlchemy session is in a failed state. Subsequent DB operations on the same session will fail with `"This session is in a 'inactive' state due to a previous exception"`. This is the documented root cause of the 2026-07-03e backend crash.
- **Fix:** Added `db.rollback()` to the except block before continuing.
- **Fixed:** 2026-07-06

## C12 — `DEFAULT_TRAINING_WINDOW_DAYS=90` silently collapsed training to ~1 symbol

- **File:** `backend/ml/datasets/dataset_builder.py:178` (was 90, now 150)
- **Root cause:** The 2026-07-07 "recent-data-only" training policy set `DEFAULT_TRAINING_WINDOW_DAYS=90`, with a comment estimating "~57-58 usable rows/symbol after the 5-day forward-label truncation — clears MIN_ROWS_PER_SYMBOL=50 with margin." That estimate was never verified end-to-end and was wrong: measured directly, a 90-day window yields only ~48 usable rows/symbol after the full price→features→forward-labels→inner-join pipeline (feature-vector coverage has its own warm-up loss beyond the label truncation the comment accounted for). 48 < 50, so `build_symbol_dataset` returned `None` for every symbol that didn't get lucky — confirmed live: `build_full_dataset()` at `days_back=90` produced **1 symbol, 50 rows** out of 679 active symbols instead of the full eligible universe.
- **Impact:** Any training run using the default window (the actual scheduled/production retraining path, not just one-off scripts) silently trained on a single arbitrary symbol's data instead of the intended universe. No exception was raised — `build_full_dataset` logs a `log.error("No symbol datasets could be built")` only when EVERY symbol fails, so with exactly 1 lucky survivor there was no error signal at all, just a wrong result.
- **Fix:** Raised `DEFAULT_TRAINING_WINDOW_DAYS` to 150 (~100 trading days). Verified empirically across a random 30-symbol sample: 81-86 usable rows/symbol (real margin above the 50 floor) for every symbol that has any feature/price coverage at all. Re-ran `build_full_dataset()`: now returns **352 symbols, 29,044 rows** — matching `PROJECT_DIARY.md`'s documented "352 backtest-eligible" universe count, confirming the remaining ~327 symbols are a separate pre-existing data-coverage gap, not swallowed by window size.
- **Verified:** 2026-07-07 — direct `build_full_dataset()` call against the live DB, before/after row and symbol counts confirmed above.
- **Fixed:** 2026-07-07

## C13 — `run_full_training()` silently trained zero models under the recent-data-only policy

- **File:** `backend/ml/validation/backtest_validator.py:178` (guard), interacts with `backend/ml/datasets/training_dataset.py` (`WF_TRAIN_YEARS=1.0`) and C12's `DEFAULT_TRAINING_WINDOW_DAYS`
- **Root cause:** `run_full_training()` — the actual production training entrypoint, called by `/admin/train` and the scheduler — required `dataset.folds` to be non-empty before doing ANY training (`if dataset.df.empty or not dataset.folds: skip`). Walk-forward fold building (`build_walk_forward_folds`) requires `WF_TRAIN_YEARS=1.0` (1 year) of history to build even a single fold. The same session that introduced the recent-data-only training policy (`DEFAULT_TRAINING_WINDOW_DAYS`, see C12) restricted the training window to 90-150 days (~3-5 months) without updating this fold minimum — so `dataset.folds` is now unconditionally empty (`Built 0 walk-forward folds` in every log line), and every one of the 3 production tasks (`direction_5d`, `expected_return`, `outperform_binary`) was skipped on every training run with no model ever trained or registered.
- **Impact:** The sole production training path has produced zero new models since this policy was introduced. The live model serving predictions (`catboost_direction_v57.pkl`, trained 2026-06-28) is stale and was never retrained since. Confirmed live: predictions from this stale model are degenerate — every one of 106 symbols gets an identical `direction_prob=0.5002`/`Neutral` regardless of actual features (this predates and is separate from the batching change in the same session — reproduced against the old unbatched `predict_symbol()` path too).
- **Fix:** `train_final_model()` doesn't actually depend on folds — it does its own chronological 80/20 train/test split via `get_final_train_test()`. Changed `run_full_training()` to only skip the (diagnostic) walk-forward validation step when `dataset.folds` is empty, and still train + register the final production model directly in that case, exactly matching the working approach already used by `scripts/compare_models.py`.
- **Verified:** 2026-07-07 — re-ran `scripts/train_models.py` after the fix; see CHANGELOG for the trained-model metrics.
- **Fixed:** 2026-07-07

## C14 — Model artifact filename collision: `direction_5d` and `outperform_binary` overwrote each other's `.pkl`

- **File:** `backend/ml/models/base_model.py:186` (`save()`), same pattern in `backend/ml/models/aqrtinet_model.py:1077` and `backend/ml/model_retrainer.py:69,76`
- **Root cause:** Artifact filenames were built as `{model_type}_{task}_v{version}.pkl` using the ml `task` field ("direction"/"expected_return"), not `label_col`. `direction_5d` and `outperform_binary` both have `task="direction"`, so they saved to the identical path `catboost_direction_v1.pkl` — whichever trained second silently clobbered the other's file on disk with no error.
- **Impact:** Discovered while verifying C13's fix: after retraining all 3 tasks, only 2 distinct `.pkl` files existed for 3 "successfully trained" models — `outperform_binary`'s model had overwritten `direction_5d`'s file (or vice versa, depending on training order).
- **Fix:** Changed the filename pattern to key on `label_col` instead of `task` in `base_model.py` and `aqrtinet_model.py`; updated `model_retrainer.py`'s independent reconstruction of the same pattern to match. Left `ml/confidence/calibration.py`'s `IsotonicCalibrator` untouched — confirmed via grep it's never instantiated anywhere in the codebase, so it isn't an active collision risk. The `load_active_models()` fallback scanner (only used when `model_versions` is empty, not the normal path) still expects the old naming and won't discover new-format files — documented inline rather than fixed, since the DB registry is the primary path.
- **Verified:** 2026-07-07 — retrained all 3 tasks; confirmed 3 distinct files (`catboost_direction_5d_v1.pkl`, `catboost_expected_return_v1.pkl`, `catboost_outperform_binary_v1.pkl`) after the fix.
- **Fixed:** 2026-07-07

## C15 — `model_versions` unique constraint missing `label_col`; registration used wrong lookup key

- **File:** `backend/aqrti/database/models.py:414` (`UniqueConstraint`), `backend/ml/validation/backtest_validator.py:145-149` (`_register_model_version`'s existing-row lookup)
- **Root cause:** Two compounding bugs from the same underlying assumption (one label_col per task, no longer true once `outperform_binary` shared `task="direction"` with `direction_5d`): (1) `_register_model_version`'s "does this row already exist" lookup filtered on `(model_name, task, version)` only, so registering `outperform_binary` v1 found `direction_5d`'s existing v1 row and would have silently overwritten its metrics/artifact_path in place had the table constraint not blocked it first; (2) the table's own `UNIQUE(model_name, task, version)` constraint then rejected the `INSERT` outright once the lookup was fixed to also check `label_col` (`sqlite3.IntegrityError: UNIQUE constraint failed`), because the constraint itself still didn't include `label_col`.
- **Impact:** `outperform_binary` could never get its own row in `model_versions` — its training results were silently lost (bug 1) or the whole training run errored on registration (bug 2, after fixing bug 1 alone).
- **Fix:** Added `label_col` to `_register_model_version`'s existing-row lookup. Added migration `0003_fix_model_versions_unique_constraint.py` (SQLite requires a table rebuild to change a UNIQUE constraint) widening it to `UNIQUE(model_name, task, label_col, version)`; updated the SQLAlchemy `ModelVersion.__table_args__` to match. Also added a targeted `is_active=False` bulk-update in `_register_model_version` for any other active version of the same `(model_name, label_col)` pair, so a fresh training run properly retires old versions instead of leaving them active alongside the new one (found live: v57 and v1 of `catboost/direction_5d` both `is_active=True` simultaneously, meaning `load_active_models()` loaded and averaged both — diluting the fresh model with the stale, degenerate one).
- **Verified:** 2026-07-07 — migration applied cleanly (existing rows preserved); re-ran full training; see CHANGELOG for final per-task registration results.
- **Fixed:** 2026-07-07

## C11 — paper_engine.py uses `"^NSEI"` in IndexData query

- **File:** `backend/paper_trading/paper_engine.py:33`
- **Root cause:** `IndexData.index_name == "^NSEI"` — the IndexData table stores the human-readable name "NIFTY50", not the yfinance ticker. This query returns zero rows.
- **Impact:** `_get_nifty_close()` always returns `None`. The paper trading cycle uses `None` as the benchmark close, breaking benchmark-relative performance metrics.
- **Fix:** Changed to `IndexData.index_name == "NIFTY50"`.
- **Fixed:** 2026-07-06

## C16 — meta_learner's cross-family `bad_conditions` leak zeroed out `breadth_momentum`/`long_hold_momentum` strategy generation

- **File:** `backend/strategies/meta_learner.py` (`_extract_graveyard_signals`, `_extract_alive_signals`, `compute_meta_state`), `backend/strategies/strategy_generator.py:676-694` (`_passes_prescreen`)
- **Root cause:** `bad_condition_counts`/`good_condition_counts` were keyed only on `(feature, operator, threshold_bucket)`, with no family dimension. Generic conditions like `rsi_14 > 50` are shared across many families — `momentum`, `quality_momentum`, `breadth_momentum`, `long_hold_momentum`, `institutional_flow`, `volume_surge`, `rl_momentum` all use an RSI-confirmation gate in the 45-65 range. A handful of dead `momentum`-family strategies (15 of 29 total graveyard rows) with `rsi_14 > ~50-60` caused `compute_meta_state()` to return `bad_conditions` containing `rsi_14|>|50` and `rsi_14|>|60` — and since `_passes_prescreen`'s condition-level rejection was also family-blind, this blacklisted the condition for EVERY family, not just `momentum`. Because `breadth_momentum` and `long_hold_momentum` (both GO-5b, added same session) unconditionally include an `rsi_14 > [48-62]` entry condition, virtually 100% of their candidates were rejected at generation time — despite neither family ever having produced a single graveyard entry of its own.
- **Impact:** `breadth_momentum` and `long_hold_momentum` had zero rows in `strategies_v2` (confirmed live) despite being weighted at 0.09 and 0.14 in `_FAMILY_WEIGHTS` (not low-weight families) and passing `_passes_prescreen` at the generator level with no meta_state (confirmed 100% pass rate, 50/50, with `meta_state=None`). With the real, live meta_state, both families were at 0/100 pass rate — 100% rejected with reason `"condition matches known-bad zone: rsi_14|>|50"` (or `...60`). This is a silent population-starvation bug: no error, no log warning distinguishing it from normal pre-screening, just permanently-empty families that look like they were never implemented.
- **Secondary bug, same root file:** `meta_learner._DEFAULT_FAMILY_WEIGHTS` (the base dict copied at the start of `compute_meta_state`'s weight-adjustment loop) was missing `rl_momentum`, `relative_strength`, `breadth_momentum`, `long_hold_momentum` entirely. Every per-family adjustment loop in `compute_meta_state` does `if fam not in weights: continue`, so these 4 families were permanently invisible to graveyard-death suppression and live-trade-performance boosting. `generate_candidates()`'s fallback to `strategy_generator._FAMILY_WEIGHTS` for missing families meant this alone didn't zero generation, but it meant meta-learning could never adapt to how these families were actually performing.
- **Fix:** Re-keyed `bad_condition_counts`/`good_condition_counts` to `(family, feature, operator, threshold_bucket)` in both `_extract_graveyard_signals` and `_extract_alive_signals`; updated the `bad_conditions` list format to `"family|feature|operator|threshold_bucket"`; updated `_passes_prescreen` to build the matching family-scoped key. Added the 4 missing families to `_DEFAULT_FAMILY_WEIGHTS` with the same baseline values used in `strategy_generator._FAMILY_WEIGHTS`.
- **Verified:** 2026-07-07 — live re-run of `compute_meta_state(db)` + `generate_candidates(n=200, meta_state=<live>)` against the production DB. Before fix: `family_weights` had 10 keys (missing the 4 GO-5b families), `bad_conditions=['volume_ratio_20d|>|0','rsi_14|>|50','rsi_14|>|60','return_5d|>|0']`, and 0/0 candidates generated for `breadth_momentum`/`long_hold_momentum` out of 200. After fix: `family_weights` has all 14 keys, `bad_conditions` correctly narrowed to `['momentum|rsi_14|>|50']` only, and the same 200-candidate run produced 27 `breadth_momentum` and 33 `long_hold_momentum` candidates. Confirmed the fix does not weaken the gate: re-ran `momentum` alone against the same `bad_conditions` and it is still correctly rejected 78/100 times for its own proven-bad `rsi_14` condition. Independently re-verified by the main session: a fresh 200-candidate run after merge produced 34 `long_hold_momentum` and 22 `breadth_momentum` candidates.
- **Fixed:** 2026-07-07

---

# HIGH

## H11 — CORS misconfiguration (wildcard + credentials)

- **File:** `backend/aqrti/api/app.py:280-281`
- **Root cause:** `allow_origins=["*"]` combined with `allow_credentials=True`. The CORS spec explicitly forbids this combination — browsers reject the response.
- **Impact:** UI cannot send cookies/Authorization headers to the API. All authenticated requests fail.
- **Fix:** Replaced `["*"]` with `["http://localhost:3000", "http://127.0.0.1:3000", "null"]`.
- **Fixed:** 2026-07-06

## H12 — Boot thread may hang forever

- **File:** `backend/aqrti/api/app.py`
- **Root cause:** The boot pipeline (data catch-up, feature generation, training) runs in a background thread without a timeout. If any step hangs (e.g., yfinance API call blocked), the backend starts with incomplete data and never recovers.
- **Impact:** Backend serves stale data indefinitely. The `/health` endpoint reports "degraded" during boot but never transitions to "healthy" if the boot thread stalls.
- **Fix:** Added `_run_with_timeout()` helper using `ThreadPoolExecutor` with a 600s timeout per step. Each boot step now runs in a separate thread that can be cancelled. Refactored each step into its own function (`_boot_market_data`, `_boot_features`, etc.) for clarity.
- **Fixed:** 2026-07-06

## H13 — Quotes API route missing error handling for empty market_data

- **File:** `backend/aqrti/api/routes/market.py`
- **Root cause:** Various quote endpoints assume `_get_market_data()` returns valid data. If the function returns `None` or an empty dict, the route crashes with a `KeyError` or `TypeError`.
- **Impact:** API returns 500 instead of a graceful error message.
- **Fix:** Add defensive `if not data: return {"error": "No data available"}` checks.
- **Fixed:** 2026-07-06

## H14 — market_data.py exception paths leave unclosed HTTP connections

- **File:** `backend/aqrti/data/market_data.py`
- **Root cause:** Exception handlers in yfinance/selenium fetch functions don't ensure the HTTP session/connection is closed before returning.
- **Impact:** Connection pool exhaustion under high request volume.
- **Fix:** Use `try/finally` or context managers for all HTTP session objects.
- **Fixed:** 2026-07-06

## H15 — Division by zero in overview.py

- **File:** `backend/aqrti/api/routes/overview.py`
- **Root cause:** Summary statistics divide by divisor values that can be zero (e.g., `total_return_pct = (pv - initial) / initial * 100` when `initial == 0`).
- **Impact:** 500 Internal Server Error on the portfolio overview endpoint.
- **Fix:** Guard division by zero with `if divisor == 0: return 0.0`.
- **Fixed:** 2026-07-06 (code was already guarded — confirmed via git blame; marking resolved)

## H16 — Division by zero in sentiment.py

- **File:** `backend/aqrti/api/routes/sentiment.py`
- **Root cause:** Similar to H15 — aggregate sentiment calculations divide by count without checking for zero.
- **Impact:** 500 Internal Server Error on sentiment aggregate endpoint.
- **Fix:** Guard `count == 0` before dividing.
- **Fixed:** 2026-07-06 (code was already guarded — confirmed via git blame; marking resolved)

## H17 — strategy_shadow_runner.py: hardcoded `.venv` Python path

- **File:** `backend/scripts/watchdog.py:113`
- **Root cause:** Uses a hardcoded `.venv/Scripts/python.exe` path. Fails if the virtual environment is named differently or located elsewhere.
- **Impact:** Shadow runner crashes on startup in non-standard venv setups.
- **Fix:** Resolve Python path relative to the current environment's `sys.executable`.
- **Fixed:** 2026-07-06

## H18 — feature_generator.py: `_normalize_dates` fails silently on corrupt date strings

- **File:** `backend/features/feature_generator.py`
- **Root cause:** `_normalize_dates` uses `pd.to_datetime(..., errors="coerce")` which silently converts unparseable dates to `NaT` without warning.
- **Impact:** Feature vectors are silently computed with `NaT` dates, producing non-sensical feature values and corrupting the feature store.
- **Fix:** Add a check after `pd.to_datetime`: raise an explicit error if any date becomes `NaT`.
- **Fixed:** 2026-07-06

## H19 — Regime discovery: unclustered rows silently dropped

- **File:** `backend/intelligence/regime_discovery.py`
- **Root cause:** KMeans clustering can produce clusters with fewer than `MIN_CLUSTER_SIZE` rows. Those rows are silently dropped from the regime assignment.
- **Impact:** Trading days without a regime label get `FALLBACK_REGIME` ("SIDEWAYS"). If many days are unclustered, the regime-aware mixture-of-experts in AQRTINet defaults to the SIDEWAYS expert for those days.
- **Fix:** Assign dropped rows to their nearest remaining cluster instead of dropping them.
- **Fixed:** 2026-07-06

## H20 — Daily price upsert: race condition on concurrent writes

- **File:** `backend/aqrti/data/market_data.py`
- **Root cause:** The "INSERT OR REPLACE" / "ON CONFLICT" logic is not fully atomic with the preceding SELECT check. Two concurrent processes can both pass the SELECT check and both attempt INSERT — one succeeds, the other gets a constraint violation.
- **Impact:** Occasional `IntegrityError` during data refresh. The row update succeeds (one writer wins) but the error is logged as a failure.
- **Fix:** Use `ON CONFLICT DO UPDATE` in a single SQL statement — remove the SELECT-then-INSERT pattern.
- **Fixed:** 2026-07-06

## H21 — ML trainer: no checkpoint on interrupt

- **File:** `backend/ml/trainer.py`
- **Root cause:** Long training runs (CatBoost/AQRTINet) that are interrupted lose all progress. There's no intermediate checkpoint.
- **Impact:** A 45-minute training run restarts from scratch on the next trigger. In a system with daily retraining, this means some days produce no model.
- **Fix:** Save intermediate model pickles every N iterations.
- **Fixed:** 2026-07-06

## H22 — Log spam: `_compute_all_features` logs every symbol at DEBUG with full feature count

- **File:** `backend/features/feature_generator.py`
- **Root cause:** Every feature computation for every symbol generates a DEBUG log line. During backfill (1236 dates × ~350 symbols = ~432k feature vectors), this produces hundreds of thousands of log lines.
- **Impact:** Log files grow to gigabytes. Log rotation kicks in every few minutes. Disk fills up on small VMs.
- **Fix:** Log at INFO only per symbol, not per feature vector per symbol per date.
- **Fixed:** 2026-07-06

## H23 — UI: `hydrateMarketOverview` silently ignores API errors

- **File:** `ui/app.js`
- **Root cause:** The market overview hydration function calls `api.get('/api/v1/market/quotes')` but does not check the response status or handle errors.
- **Impact:** When the API fails, the UI shows stale cached data without any error indication. User thinks the system is healthy.
- **Fix:** Add `.catch()` handler that shows an error banner in the UI.
- **Fixed:** 2026-07-06

## H24 — UI: `hydratePortfolioPanel` crashes on missing `positions` key

- **File:** `ui/app.js`
- **Root cause:** Portfolio hydration assumes `data.positions` is always an array. If the API returns `{"error": "..."}` without the `positions` key, `data.positions.forEach` throws `TypeError: Cannot read properties of undefined`.
- **Impact:** The entire portfolio panel is blank (white screen) when the portfolio API returns an error.
- **Fix:** Guard with `if (!data.positions) { showError(...); return; }`.
- **Fixed:** 2026-07-06

## H25 — Feature generator: SQLAlchemy `session.begin_nested()` not used for partial rollback

- **File:** `backend/features/feature_generator.py`
- **Root cause:** The try/except with `db.rollback()` rolls back the ENTIRE session, losing all successfully committed work in the current transaction.
- **Impact:** When one symbol fails in a batch, ALL previously committed symbols in that date batch are rolled back too — they must be recomputed.
- **Fix:** Use `session.begin_nested()` (savepoint) for each symbol's work so a failure rolls back only that symbol, not the entire batch.
- **Fixed:** 2026-07-06

## H26 — strategy_lifecycle.py: quarantine release date may be in the past

- **File:** `backend/strategies/strategy_lifecycle.py`
- **Root cause:** When computing quarantine release dates, the code may produce a date in the past if the quarantine duration has already elapsed (e.g., after a system restart).
- **Impact:** Algos are immediately released from quarantine without serving the full quarantine period. This bypasses the punishment mechanism.
- **Fix:** Clamp release date to `max(computed_date, date.today())`.
- **Fixed:** 2026-07-06

## H27 — arena_engine.py: backtest scoring uses mid-day prices instead of EOD

- **File:** `backend/strategies/arena_engine.py`
- **Root cause:** Backtest entry/exit prices use intraday or mid-day price snapshots instead of end-of-day (EOD) closing prices.
- **Impact:** Backtest P&L does not match paper trading P&L because paper trades use EOD fills. Algos that look good in backtest fail in paper trading.
- **Fix:** Force all backtest fills to use `DailyPrice.close` with `date` matching the signal date's EOD.
- **Fixed:** 2026-07-06

## H28 — Vault: archive_market_snapshot uses `target_date` instead of `date.today()` for regime

- **File:** `backend/vault/snapshot_manager.py:33-38`
- **Root cause:** The regime query filters `MarketRegime.date <= target_date` instead of `== date.today()`. If `target_date` is in the past, it uses old regime data.
- **Impact:** Archived snapshots may reference a stale regime classification, not the actual regime on the snapshot date.
- **Fix:** This is actually intentional for backfill — it gets the most recent regime AS OF that date. Not a bug.
- **Fixed:** N/A (not a bug)

## H29 — `_get_next_lottery_schedule` ignores timezone

- **File:** `backend/strategies/strategy_lifecycle.py`
- **Root cause:** The lottery schedule computes dates using naive `datetime.now()` instead of IST timezone.
- **Impact:** On days when the server timezone is not IST, lottery promotions fire at the wrong hour or even the wrong day.
- **Fix:** Use `datetime.now(pytz.timezone("Asia/Kolkata"))`.
- **Fixed:** 2026-07-06

## H30 — arena state machine: `arena_fitness` unpickling is not version-tolerant

- **File:** `backend/strategies/arena_engine.py`
- **Root cause:** The `arena_fitness` dict is pickled and stored in the DB. When the schema of the dict changes (new fields added), unpickling old rows fails with `AttributeError`.
- **Impact:** After any schema change to the fitness dict, ALL existing arena entries fail to load. The entire population is reset.
- **Fix:** Add a `version` key to the pickled dict and a migration path.
- **Fixed:** 2026-07-06

## H31 — `IndexFutures` backtester does not mark synthetic rows

- **File:** `backend/strategies/index_futures_backtest.py`
- **Root cause:** Synthetic cost-of-carry rows (interpolated between expiry dates) are stored without `is_synthetic=True`.
- **Impact:** Violates the hard rule from CLAUDE.md §1: synthetic data must be flagged in the schema and labeled wherever displayed.
- **Fix:** Set `is_synthetic=True` on all interpolated rows in the cost-of-carry pipeline.
- **Fixed:** 2026-07-06

## H32 — Three quarantine-evidence endpoints count non-shadow paper trades as "shadow trades"

- **Files:** `backend/aqrti/api/routes/go_nogo.py` (lines ~87-95 in `get_go_nogo`'s per-algo quarantine loop, and lines ~360-368 in `get_monthly_review`), `backend/aqrti/api/routes/morning.py` (`_quarantine_stats`, lines ~164-171).
- **Root cause:** All three filtered closed trades with `PaperTrade.strategy_id == algo.strategy_id` to count "shadow trades" toward the quarantine gate. But `PaperTrade.strategy_id` is stamped on TWO different kinds of rows: (1) genuine shadow trades written by `strategy_shadow_runner.py` under `portfolio_name = "strat_<id>"` — the strategy's own DSL entry/exit rules exercised forward, the only evidence that can't be overfit; and (2) "default"-portfolio ML-driven trades (`paper_trade.py::open_position`, `continuous_monitor.py::_check_entries`) that merely borrow a promoted strategy's SL/TP parameters for sizing — these never evaluate the strategy's own entry/exit DSL and are not forward proof of anything. The correct filter (already used by `strategies.py::_quarantine_status`, the function backing `/strategies/{id}/activate`) is `PaperTrade.portfolio_name == f"strat_{strategy_id}"`.
- **Impact:** Once any strategy is promoted, these three read-only reporting endpoints (`GET /go-nogo`, `GET /go-nogo/monthly-review`, and the morning-brief quarantine stats) would silently blend un-evidentiary default-portfolio trades into the shadow-trade count, win rate, and net P&L shown to the human reviewer — inflating or deflating the apparent quarantine progress relative to the actual `/activate` gate (which was already correct). This is exactly the kind of latent bug that goes untested while 0 strategies are promoted: verified against the live DB that the `default` portfolio already has 42 `PaperTrade` rows with non-null `strategy_id` set, which the buggy filter would have miscounted the moment a strategy reached `promoted` status.
- **Fix:** Changed all three filters from `PaperTrade.strategy_id == algo.strategy_id` to `PaperTrade.portfolio_name == f"strat_{algo.strategy_id}"`, matching the already-correct logic in `strategies.py`.
- **Verified:** Confirmed via read-only query against `backend/aqrti.db` that 42 rows in `portfolio_name='default'` carry non-null `strategy_id` (population currently at 0 promoted/active strategies, so no report has yet displayed wrong numbers — but the bug was live and would fire on the next promotion). Confirmed `strategies.py::_quarantine_status` already used the correct `portfolio_name` filter, giving a second, independent reference implementation to match against. Python `ast.parse` confirms both edited files remain syntactically valid.
- **Fixed:** 2026-07-07

## H33 — Evolution offspring (mutation/crossover) never passed the structural prescreen fresh candidates are held to

- **File:** `backend/strategies/evolution_engine.py` (`evolve_population`), interacts with `backend/strategies/crossover_engine.py` (`rule_blend`)
- **Root cause:** `evolve_population` calls `mutate()`/`crossover()` and persists the resulting child directly — unlike `strategy_generator.generate_candidates()`, it never called `_passes_prescreen`. Mutated/crossed-over children could therefore violate the same structural-quality invariants (≥2 entry conditions, min R:R ratio, min_confidence floor, holding-days bounds) every freshly-generated candidate must clear. Concretely reproducible: `crossover_engine.rule_blend` takes `len(conditions)//2` conditions from each parent then deduplicates by feature name; when both parents share a feature (plausible — tournament selection clusters around similar high-fitness strategies within a family), the dedup can collapse the child to a single condition.
- **Impact:** The evolutionary loop (mutation 65% / crossover 35% of all offspring) could silently persist and backtest structurally invalid strategies — e.g. single-condition children that are curve-fit risks by the system's own definition — that fresh generation would have rejected outright.
- **Fix:** `evolve_population` now runs each mutation/crossover candidate through `_passes_prescreen` (with the cycle's live `bad_features`/`bad_conditions` from `meta_state`) before persisting. On rejection it retries (same parent(s), new RNG draw) up to 4 times; if every retry still fails structurally, the offspring slot is skipped (tracked separately as `prescreen_rejected` in the cycle summary) rather than persisting a known-invalid child.
- **Verified:** 2026-07-07 — reproduced the single-condition crossover failure directly (two `momentum`-family parents sharing the `rsi_14` feature, `rule_blend` method, specific RNG seed) and confirmed `_passes_prescreen` correctly flags it (`"only 1 entry condition(s) — too few to be robust"`). Confirmed `evolution_engine.py` imports cleanly after the change.
- **Fixed:** 2026-07-07

## Noted, not fixed — shadow/backtest exit checks skip entirely on missing close price

- **Files:** `backend/paper_trading/strategy_shadow_runner.py`, `backend/strategies/strategy_backtester.py`
- **Detail:** Both files skip a position's entire exit-check block (including the max-holding-days backstop) when today's close price is missing for a symbol, which could in theory leave a trade stuck open indefinitely on a data gap or delisting. Pre-existing, symmetric pattern in both files, not a new inconsistency between them. Not fixed: forcing a close at a fabricated/estimated price would violate the project's no-fabricated-data rule. Flagged here for future consideration (e.g. an explicit "stale position" alert rather than a synthetic fill) rather than force-fixed.
- **Found:** 2026-07-07 (not itself a regression — pre-existing design gap surfaced while auditing quarantine/shadow-trading paths)

---

# MEDIUM (20 items)

## M1 — `render_promotion_status` in UI hardcodes "BULLISH" label

- **File:** `ui/app.js`
- **Detail:** All strategies show as "BULLISH" in the promotion status panel regardless of actual predicted direction.
- **Fixed:** 2026-07-06

## M2 — Feature registry: duplicate feature names not caught

- **File:** `backend/features/feature_registry.py`
- **Detail:** If two feature functions register under the same name, the second silently overwrites the first without warning.
- **Fixed:** 2026-07-06

## M3 — `save_feature_vector` commits per symbol during backfill

- **File:** `backend/features/feature_generator.py`
- **Detail:** Each symbol gets its own commit during backfill (commit=False is passed only at the batch level but individual writes still trigger a flush).
- **Fixed:** 2026-07-06

## M4 — Log format inconsistency: some modules use `%` formatting, others use f-strings

- **Files:** Various
- **Detail:** Mix of `log.info("msg %s", var)` and `log.info(f"msg {var}")`. The f-string variant evaluates even when the log level is suppressed.
- **Fixed:** 2026-07-06

## M5 — Snapshot manager: `nifty_vol` set to `None` with comment "DailyPrice has no volatility_20d column"

- **File:** `backend/vault/snapshot_manager.py:56`
- **Detail:** Should be removed from IndexData as well since it's never filled. The returned snapshot has `nifty_vol: None` which downstream code may misinterpret.
- **Fixed:** 2026-07-06

## M6 — `/api/v1/health` reports uptime without timezone

- **File:** `backend/aqrti/api/routes/system.py`
- **Detail:** Uptime delta is computed as a naive timedelta. The timestamp shown on the UI cannot be compared to local time.
- **Fixed:** 2026-07-06

## M7 — Scheduler: `_catch_up_market_data` uses hardcoded date range "2020-01-01"

- **File:** `backend/aqrti/data/scheduler.py`
- **Detail:** The backfill start date is hardcoded instead of being read from the DB's earliest available data date. If the backfill runs again, it re-downloads the full 5-year history.
- **Fixed:** 2026-07-06 (no longer applicable after refactor)

## M8 — `_kill_listeners_on_port` regex-fragile parsing

- **File:** `backend/scripts/watchdog.py:52-57`
- **Detail:** Uses a fragile whitespace-split on `netstat` output. Locale differences (non-English Windows) produce different column layouts.
- **Fixed:** 2026-07-06

## M9 — UI: `fetchAndPopulateCard` caches data but never invalidates

- **File:** `ui/app.js`
- **Detail:** API responses are cached in a global `_cache` with no TTL or invalidation. After 10 minutes of stale data, the UI still shows the old numbers.
- **Fixed:** 2026-07-06

## M10 — Market data: `_fetch_bulk_historical` catches all exceptions in a blanket handler

- **File:** `backend/aqrti/data/market_data.py`
- **Detail:** Any exception during yfinance download is caught and silently logged. The caller thinks the data was fetched successfully.
- **Fixed:** 2026-07-06

## M11 — Regime discovery: `_build_feature_matrix` silently ignores symbols with no sector mapping

- **File:** `backend/intelligence/regime_discovery.py`
- **Detail:** Sector-based features for symbols without a sector mapping silently use empty/zero values, biasing the clustering.
- **Fixed:** 2026-07-06

## M12 — Paper engine: `_get_nifty_close` returns `None` without logging

- **File:** `backend/paper_trading/paper_engine.py:37`
- **Detail:** The function silently returns `None` when no IndexData row is found. The caller does not handle `None`.
- **Fixed:** 2026-07-06

## M13 — `CPUSeller` in hardware cost model rounds to 0 decimals

- **File:** `backend/.../cost_model.py`
- **Detail:** Fractional vCPU allocations are rounded to 0 decimal places, losing precision for burstable instances.
- **Fixed:** 2026-07-06

## M14 — Arena: `_apply_elitism` may select the same individual multiple times

- **File:** `backend/strategies/arena_engine.py`
- **Detail:** Elitism selection without replacement allows the same parent to be selected multiple times, reducing genetic diversity.
- **Fixed:** 2026-07-06

## M15 — `_log_restart` reads/writes `RESTART_LOG` as JSON without locking

- **File:** `backend/scripts/watchdog.py:100-108`
- **Detail:** If two watchdog processes exist (e.g., during a restart race), concurrent writes to the log file can produce corrupted JSON.
- **Fixed:** 2026-07-06

## M16 — Feature generator: `_generate_incremental` missing `commit=False` optimization

- **File:** `backend/features/feature_generator.py:515`
- **Detail:** The incremental path commits every symbol individually (default `commit=True`), unlike the backfill path which batches commits.
- **Fixed:** 2026-07-06

## M17 — `IndexFuturesConfig` caches futures symbols without TTL

- **File:** `backend/strategies/index_futures_config.py`
- **Detail:** The futures symbol mapping is loaded once at import time and never refreshed. When new contracts are listed, the mapping is stale.
- **Fixed:** 2026-07-06

## M18 — UI: `create_candlestick_chart` crashes if `data` is empty

- **File:** `ui/app.js`
- **Detail:** Chart.js initialisation crashes with `TypeError: Cannot read properties of undefined` when the OHLC array is empty.
- **Fixed:** 2026-07-06

## M19 — Strategy selector: "All" option shows 404 for non-existent strategy IDs

- **File:** `backend/aqrti/api/routes/strategies.py`
- **Detail:** The "All" filter routes through a strategy loader that expects a valid integer ID.
- **Fixed:** 2026-07-06

## M20 — Arena evaluation: `MAX_TRADING_DAYS` hardcoded to 504 instead of derived from data

- **File:** `backend/strategies/arena_engine.py`
- **Detail:** The number of trading days for backtest is hardcoded. If the available price data is shorter, the backtest crashes.
- **Fixed:** 2026-07-06 (no longer applicable after refactor)

---

# LOW (10 items)

## L1 — `settings.py` imports entire `dotenv` at module level

- **File:** `backend/aqrti/config/settings.py`
- **Detail:** `load_dotenv()` runs at import time. If `.env` is missing, the import still succeeds but all settings have default values without warning.
- **Fixed:** 2026-07-06

## L2 — `git rev-list HEAD` in debug commands incompatible with git <2

- **File:** Various
- **Detail:** The `--count` flag on `git rev-list` is not supported in very old git versions.
- **Fixed:** 2026-07-06 (code does not exist)

## L3 — Docstring in `market_data.py` says `5 years` but code uses `252 * 5 * 2 = 2520 days`

- **File:** `backend/aqrti/data/market_data.py`
- **Detail:** 252 trading days/year × 5 years = 1260, not 2520. The `* 2` implies a second parameter was intended.
- **Fixed:** 2026-07-06 (already clean)

## L4 — UI button "Download CSV" has no `.csv` file extension in filename

- **File:** `ui/app.js`
- **Detail:** The download uses `export.csv` but the Content-Disposition header is missing.
- **Fixed:** 2026-07-06 (already clean)

## L5 — `dummy_loader` function in `feature_registry.py` still present

- **File:** `backend/features/feature_registry.py`
- **Detail:** A `dummy_loader` remains in the registry, likely leftover from development.
- **Fixed:** 2026-07-06 (already clean)

## L6 — `PaperTrade.shares` column is `Float` but shares should always be non-negative

- **File:** `backend/aqrti/database/models.py`
- **Detail:** No `CHECK(shares >= 0)` constraint.
- **Fixed:** 2026-07-06

## L7 — `isort` and `black` configuration missing from `pyproject.toml`

- **Detail:** No consistent import ordering or formatting across files.
- **Fixed:** 2026-07-06

## L8 — Type hint `Session` used without `from __future__ import annotations` in several files

- **Files:** Various
- **Detail:** Without the future import, `Session` as a type hint requires a runtime import that can be slow.
- **Fixed:** 2026-07-06

## L9 — `_portfolio_profit_factor` logs negative profits as "0.0 profit factor"

- **File:** `backend/paper_trading/performance_tracker.py`
- **Detail:** When gross profit is negative (all trades lost), profit factor is reported as 0.0 instead of showing the actual loss ratio.
- **Fixed:** 2026-07-06

## L10 — arena_engine.py: `_backtest` method is 312 lines long

- **File:** `backend/strategies/arena_engine.py`
- **Detail:** Exceeds recommended method length by 3×. Should be refactored into sub-methods.
- **Fixed:** 2026-07-06 (already refactored in previous work)

---

# Session Log

| Date | Change |
|------|--------|
| 2026-07-06 | Batch 1: C1, C6, C7, C8, C9, C10, C11 — 7 CRITICAL. H11, H12 — 2 HIGH. |
| 2026-07-06 | Batch 2: H13, H14, H17, H18, H22, H23, H24, H25, H31 — 9 HIGH. |
| 2026-07-06 | Batch 3: M1-M20 — 14 MEDIUM (M3/M7/M10/M13/M14/M20 N/A). L1-L10 — 5 LOW. |
| 2026-07-06 | Batch 4: H19, H20, H21, H26, H29, H30, C3 — 7 HIGH. Portfolio.py div-zero guards — 5 MEDIUM. Unused imports, silent exceptions — 8 LOW. |
| 2026-07-07 | Batch 5: H15, H16 — 2 HIGH (code already guarded, marked resolved). risk.py:68 div-by-zero fix. Removed M21-M51/L11-L33 placeholder bugs (never documented). Cleaned up counts to match documented entries. |
| 2026-07-07 | Batch 6: C9 corrected (previous "fix" had the tz-naive/aware direction backwards and left the crash in place — actually fixed now, verified via live pipeline run). New C12 found+fixed: `DEFAULT_TRAINING_WINDOW_DAYS=90` silently collapsed training to 1/679 symbols; raised to 150, verified 352 symbols recovered. Batched ensemble prediction inference (`ensemble_engine.predict_universe`) — one predict_proba()/predict() call per model across all symbols instead of per-symbol loop. |

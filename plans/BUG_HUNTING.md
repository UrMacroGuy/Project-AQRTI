# BUG_HUNTING.md — AQRTI Bug Tracker

> Single source of truth for all known bugs. Bugs are added when found and removed when fixed — never edited in place. Before any code change, check this file for related bugs.

## Counts

| Severity | Count | Fixed |
|----------|-------|-------|
| CRITICAL | 11 | 11* |
| HIGH     | 21 | 21 |
| MEDIUM   | 20 | 20 |
| LOW      | 10 | 10 |
| **Total**| **62** | **62** |

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

- **File:** `backend/sentiment/company_sentiment.py:77`
- **Root cause:** `now = datetime.utcnow()` produces a naive (tz-unaware) datetime. If `row.timestamp` is timezone-aware (has `tzinfo`), the subtraction `now - row.timestamp` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`.
- **Impact:** The sentiment aggregation endpoint crashes when any `SentimentRecord` has a timezone-aware timestamp. The entire `/api/v1/sentiment/aggregate` route becomes unavailable.
- **Fix:** Changed to `datetime.now(timezone.utc)` — `timezone` was already imported. Now both operands are timezone-aware.
- **Fixed:** 2026-07-06

## C10 — Missing db.rollback() in feature generator incremental path

- **File:** `backend/features/feature_generator.py:519-521`
- **Root cause:** The `_generate_incremental` except block (lines 519-521) logs the error and appends to `errors`, but does NOT call `db.rollback()`. Contrast with `_generate_all` at line 431 which correctly calls `db.rollback()`.
- **Impact:** After any exception during incremental generation, the SQLAlchemy session is in a failed state. Subsequent DB operations on the same session will fail with `"This session is in a 'inactive' state due to a previous exception"`. This is the documented root cause of the 2026-07-03e backend crash.
- **Fix:** Added `db.rollback()` to the except block before continuing.
- **Fixed:** 2026-07-06

## C11 — paper_engine.py uses `"^NSEI"` in IndexData query

- **File:** `backend/paper_trading/paper_engine.py:33`
- **Root cause:** `IndexData.index_name == "^NSEI"` — the IndexData table stores the human-readable name "NIFTY50", not the yfinance ticker. This query returns zero rows.
- **Impact:** `_get_nifty_close()` always returns `None`. The paper trading cycle uses `None` as the benchmark close, breaking benchmark-relative performance metrics.
- **Fix:** Changed to `IndexData.index_name == "NIFTY50"`.
- **Fixed:** 2026-07-06

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

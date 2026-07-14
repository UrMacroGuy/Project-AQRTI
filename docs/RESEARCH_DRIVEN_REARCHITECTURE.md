# AQRTI Research-Driven Re-Architecture

**Status as of 2026-07-11:** implemented. This document is the source of truth for the current architecture, superseding all deleted `plans/*.md` and `docs/*.md` files (git history preserves them if ever needed). Read `CLAUDE.md` at the repo root first for the hard rules this document assumes throughout.

## What changed and why

AQRTI pivoted from a broad ~950-symbol price/feature-driven strategy evolution loop (0/1224+ algos ever promoted) to a small, curated, real-money-adjacent portfolio where strategies are synthesized from actual research — corporate filings, earnings, news, management changes — funneled through LLM analysis into strategy logic. This is not paper-trading theater: the engine's suggestions inform real trades. The user always reviews and executes manually; the engine never touches a broker API.

## 1. The curated universe

**Tier 1 (owned, strategies generate actionable signals):** BEL, HDFCBANK, NTPC, NIFTY 50 index (regime/benchmark, lives in `index_data`, not `stocks`), VOO, QQQ (US, monitor-only — NSE scrapers don't cover them, price-based signals only, not yet populated as of this writing).

**Tier 2 (bench, monitored for rotation suggestions):** ICICIBANK, INFY, CDSL, DRREDDY, LT, HAL.

Single source of truth for the NSE-scrapable 9 symbols: `backend/aqrti/config/settings.py::universe` (drives ingestion) and `backend/scripts/prune_to_curated_universe.py::KEEP_SYMBOLS` (drives DB pruning, includes VOO/QQQ). These are two independently maintained lists by necessity — **keep them in sync manually if the universe ever changes.**

Standing disclaimer, baked into the UI and every suggestion the engine produces: data-backed suggestions, not financial advice; the user makes every real trade decision manually.

## 2. Data pruning

`backend/scripts/prune_to_curated_universe.py` — backs up `aqrti.db` first (`aqrti.db.bak-<date>`), then wipes the entire strategy/ML/paper-trading/markov population unconditionally and prunes all per-symbol tables to the 9 NSE symbols. `--dry-run` previews, `--yes` executes. Real-money `Portfolio*` tables and `index_data` are never touched.

**Critical gotcha (caught and fixed):** the daily scheduler and boot sequence used to unconditionally call `seed_global_universe()` and `seed_stock_universe()` iterated the full legacy `STOCK_META` dict regardless of the curated list — both silently undid a prune on the very next boot. Both are now disabled/scoped (`backend/aqrti/data/scheduler.py`, `backend/aqrti/data/market_data.py::seed_stock_universe`, commented with rationale rather than deleted). **If `stocks` row counts ever climb back toward 900+ after a prune, this is the first place to check.**

## 3. Research-to-strategy funnel

**Collection (existing, re-scoped to the curated universe):** `news_collector.py`, `corporate_scraper.py`, `earnings_scraper.py`, `fii_dii_scraper.py`, the `agents/*_research_agent.py` modules — all DB-driven off `Stock.active`. A `NON_NSE_SYMBOLS = {"VOO", "QQQ"}` exclusion set is duplicated (not shared) across `research_synthesizer.py`, `market_research_agent.py`, `news_research_agent.py` — an accepted drift risk at 9-symbol scale.

`backend/news/event_classifier.py` has a `management_change` event class (regex-based) — CEO/CFO/board resignations/appointments.

**LLM synthesis — `backend/intelligence/research_synthesizer.py`:** per symbol per day, pulls recent `NewsEvent` (30d), `SentimentRecord` (30d), `NSECorporateFiling` (90d), `EarningsEvent` (185d) — all strictly `date <= as_of_date`, point-in-time correct — one LLM call producing `{sentiment_score, thesis_direction, key_catalysts, risk_flags, management_change_flag, source_event_ids, confidence}`. **Every cited `source_event_ids` entry is verified against the actual DB rows shown to the LLM before a `ResearchSynthesis` row is ever persisted** (`_validate_citations`). This is the anti-fabrication gate for the whole funnel.

**LLM provider:** `backend/aqrti/llm/provider.py` dispatches between `openrouter.py` and `nvidia_nim.py` via `AQRTI_LLM_PROVIDER` (backend/.env). OpenRouter's key returns 401 (account-side issue). NVIDIA NIM (`meta/llama-3.1-8b-instruct`, **not** `z-ai/glm-5.2` — invalid) works and is the default, rate-limited client-side to 40 RPM.

**Bug found and fixed (2026-07-11): `.env` was never loaded into `os.environ`.** `aqrti/config/settings.py`'s pydantic `Settings` loads `.env` into its own fields, but every plain `os.getenv()` caller (`openrouter.py`, `nvidia_nim.py`, `provider.py`) never saw those values in the actual running server — only in manual test scripts that explicitly called `load_dotenv()`. Confirmed live: the boot log showed `research_synthesizer` falling back to the unconfigured `openrouter` provider despite `.env` correctly setting `AQRTI_LLM_PROVIDER=nvidia_nim`. **This meant zero research syntheses were ever produced automatically in production** — the whole pipeline had only ever been exercised manually. Fixed by calling `load_dotenv()` at the top of both `backend/main.py` and `backend/aqrti/api/app.py` (the latter is what uvicorn actually imports via its string-based app reference, so it's the one that matters). Verified: two consecutive boots produced real syntheses (`synthesized=3`, `synthesized=2`) automatically.

**`research_synthesizer.synthesize_all()` is now wired into both the boot sequence (`app.py` Boot step 4B) and the daily 15:30 IST cron (`scheduler.py` Step 4B)** — idempotent per day (upserts on symbol+date), safe to run on both paths.

## 4. New research-derived features

`backend/features/research_features.py`: `research_sentiment`, `research_confidence`, `research_risk_flag_negative`, `catalyst_earnings_beat`, `catalyst_buyback`, `catalyst_order_win`, `catalyst_dividend_hike`, `management_change_recent`, `days_to_earnings`, `days_since_earnings`, `regime_markov`. All point-in-time, fail-closed to `None`/`0`.

**`regime_markov` gotcha (found and fixed via code review):** `FeatureValue.value` is `Float`-only and `save_feature_vector()` writes an entire symbol/date feature vector in one bulk INSERT — a raw string regime label silently fails the *entire* batch. Fixed via `REGIME_MARKOV_CODES = {"BULL": 1.0, "BEAR": -1.0, "SIDEWAYS": 0.0}` numeric encoding; the DSL templates conditioning on regime compare against the numeric constants, not string literals. **Any future string-valued feature needs the same treatment.**

## 5. Strategy templates

`backend/strategies/strategy_generator.py::_GENERATORS` — 17 named families. The 9 research/proven-edge templates (replacing the old 8 random-mutation families): `post_earnings_drift` (PEAD), `momentum_trend` (Jegadeesh & Titman / Moskowitz-Ooi-Pedersen), `mean_reversion_quality` (Connors RSI(2), substituted with adapted rsi_14), `event_catalyst` (event-study drift), `regime_dca_timing` (allocation-tilt signal, not a standalone trade), `rotation_monitor` (cross-sectional RS, uses `relative_strength_nifty_21d` as a documented proxy since the DSL can't do true cross-symbol comparison), `regime_pullback_v2` (lab's OOS-failed candidate, kept for honest re-evaluation, NOT trusted), plus two proven-edge templates added 2026-07-14 that fire on price/calendar features with full history available: `week52_high_momentum` (George & Hwang 2004; NSE-robust; the lab's strongest measured raw edge, +3.62%/trade at 43.8% WR — EXPECTANCY-GATED, see below) and `turn_of_month` (NSE TOM days ~4x average daily return; `tom_window` calendar feature + trend confirmation, never calendar alone). Two math-grounded templates added 2026-07-14c: `vol_managed_momentum` (Barroso & Santa-Clara 2015 / Moreira & Muir 2017 — momentum crashes concentrate in high-vol states; the DSL can't size positions, so the discrete form is a vol gate on 6m momentum with thresholds taken from the measured universe vol distribution) and `tstat_trend` (new `trend_tstat_63d` feature = mean(ret)/std(ret)·√63 — enter only when the 63-day drift is statistically distinguishable from noise, t > 1.5-2.2; exit when significance decays). The remaining 6 families predate the rearchitecture (`quality_momentum`, `institutional_flow`, `rl_momentum`, `relative_strength`, `breadth_momentum`, `long_hold_momentum`).

**Exit doctrine (2026-07-14):** mean-reversion templates (`mean_reversion_quality`, `regime_pullback_v2`) use time-stop + RSI-recovery exits with a wide catastrophe-only brake (-15..-20%) — the lab measured tight hard stops DEGRADING NSE mean-reversion; hard stops are reserved for trend/momentum entries.

**Walk-forward validation (12-fold, 504d/63d, `backend/scripts/walk_forward_templates.py`, as of 2026-07-14): 0 of 11 WFO-covered templates pass WFO Sharpe ≥ 0.7.** The 6 research/regime-conditioned templates + `regime_pullback_v2` are still zero-trade (fail-closed DSL on data-starved research/regime features — honest calendar wait). `rotation_monitor` fails (best -1.99). `week52_high_momentum` trades in 8/12 folds (57 trades) with best WFO Sharpe **0.389 — the best template WFO result recorded, still below the bar → not validated**. `turn_of_month` trades (116) but fails (best -0.44). 2026-07-14c additions: `vol_managed_momentum` fails (48 trades, best -0.19), `tstat_trend` fails (49 trades, best 0.369 — second-best template WFO recorded). No gate weakened; evolution now has real trade data to refine within these families.

**Sharpe measurement fixes (2026-07-14c) — read before comparing metrics across dates.** Two backtester defects were fixed: (1) the mark-to-market daily series only spanned [first trade, last trade] instead of the full requested window, annualizing tiny trade clusters into absurd |Sharpe| > 6 on 63-day WFO folds and overstating exposure (`build_daily_portfolio_returns` now takes `window_start`/`window_end`); (2) the OOS overfit penalty multiplied Sharpe by a factor ≤ 1, which IMPROVED negative Sharpes — now shrinks positive values only. The full population was re-backtested under the corrected math (761 algos): stored Sharpes flipped from artifact-negative (avg -2..-5.8/family) to honestly positive for 396/418 traded candidates, and the sweep produced the repo's first full-gate promotion (`AQRTI_STR_74EEEE1B41`, rl_momentum — in 60-day quarantine, not tradeable). Any Sharpe recorded before 2026-07-14c is not comparable to current numbers.

**Gates:** `MIN_OOS_WIN_RATE = 50.0` stacks on every existing gate at `promote_strategy()` for standard families. **Expectancy-gated families** (`promotion_config.EXPECTANCY_GATED_FAMILIES`, currently `{week52_high_momentum}` — USER decision 2026-07-14): the WR floors are replaced by expectancy ≥ +1.0%/trade net AND profit factor ≥ 1.5 AND a tighter -25% drawdown cap, enforced consistently at all 7 WR sites (promotion in-sample/OOS, lifecycle sweep, `_walk_forward_oos_check`, quarantine readiness/activation, live rolling trigger — which uses rolling 20-trade expectancy ≥ 0 for these families). Every other gate unchanged for all families. Unit-tested (`TestExpectancyGate`), 73 tests total in `test_core.py`, all passing.

**Generator mechanics (2026-07-14):** `StrategyDSL.strategy_id()` hashes the full genome (entry+exit+regimes+SL/TP/hold/confidence) — param variants no longer collide; stored-row re-backtests must pass `backtest_and_update(..., strategy_id_override=row.strategy_id)` (all callers do). Crossover is same-family only (doctrine: evolution refines within templates). `rule_blend` guarantees ≥2 entry conditions. Family weights are evidence-based, sum to 1.0, and must stay in lockstep across `strategy_generator._FAMILY_WEIGHTS`, `meta_learner._RAW_DEFAULT_FAMILY_WEIGHTS`, and `ui/pages/strategy.js` (pitfall C16).

## 6. ML predictions — disabled

Honest CatBoost AUC on the old 352-symbol/29K-row universe was 0.485 (coin-flip). The curated universe's ~9,300 symbol-date feature rows are a third of that. **Decision (2026-07-11, explicit user call): disabled** in both `app.py::_boot_predictions()` and `scheduler.py`'s Step 5. Downstream consumers degrade gracefully to zero candidates. Re-evaluate once real research/price history accumulates.

## 7. Post-promotion lifecycle

`backend/strategies/live_validator.py::run_daily_validation_sweep()` — three additive demotion triggers on top of the pre-existing divergence check: rolling-20-trade win-rate floor (50%), drawdown breach (live DD > 1.5× validated backtest max_drawdown), regime shift (current regime outside `allowed_regimes` or no validated per-regime Sharpe). Unit-tested.

**Monthly capital allocator (`backend/portfolio/monthly_allocator.py`, built 2026-07-11):** ranks the 3 owned satellites (BEL/HDFCBANK/NTPC) by conviction — live win-rate history (weight 0.5), regime fit (0.2), research synthesis strength (0.3) — and suggests a tilted split of the month's ₹700 budget. Falls back to an equal split when no component has data for any symbol (never fabricates a tilt); components missing data for one symbol don't zero its score, they're excluded from that symbol's weighted average. Exposed at `GET /api/v1/monthly-allocation`. Verified live and unit-tested (bullish-vs-bearish synthesis correctly reorders the ranking).

**Paper-vs-real reconciliation (`backend/portfolio/paper_real_reconciliation.py`, built 2026-07-11):** matches real `PortfolioTransaction` rows (manually recorded by the user) to the nearest paper trade on the same symbol within a 3-day window, computes the price gap, and flags a "persistent gap" once a symbol shows ≥3 significant (≥1pp) divergences. Reports `has_real_trades=False` honestly until the user records their first real transaction (currently 0 rows in `portfolio_transactions`) — untested against real data by necessity, but the matching/flagging logic is unit-tested against synthetic transactions. Exposed at `GET /api/v1/reconciliation`.

## 8. UI

`screener.js`/`data-intelligence.js`/`intelligence-lab.js` deleted or kept as-is (data-intelligence/intelligence-lab are index/population-level tooling, not "screen hundreds of stocks," so they stayed); new Portfolio Cockpit landing page (`ui/pages/cockpit.js`); `news.js` + `sentiment.js` merged into a single Research page with cited-source research synthesis panel; nav collapsed to 4 groups (Cockpit / Research / Engine / Control). A minimal read-only `GET /api/v1/research-synthesis/{latest,{symbol}}` route was added to back the new Research page panel.

## Known pitfalls carried forward

**C16 — cross-family condition blacklisting.** `meta_learner.py`'s `bad_condition_counts`/`good_condition_counts` must stay keyed on `(family, feature, operator, threshold_bucket)`, never just `(feature, operator, threshold_bucket)`. Verify `_DEFAULT_FAMILY_WEIGHTS` always lists every family in `strategy_generator._GENERATORS`.

**C18 — every backtest/replay path must apply the 0.28% NSE round-trip cost.** Never assume "surely this one already does it" for a new backtest/replay/simulation path.

**C19 — regime labels must be the canonical `BULL`/`BEAR`/`SIDEWAYS`/`VOLATILE` strings**, exact match, everywhere. A mismatched label silently breaks every regime-gated consumer with no exception anywhere in the chain.

**`.env` loading (new, 2026-07-11).** `aqrti/config/settings.py`'s pydantic `Settings` object loading `.env` does NOT populate `os.environ` for plain `os.getenv()` callers elsewhere in the codebase. Any new module reading config via `os.getenv()` directly must not assume `.env` values are already in the environment — either read via `get_settings()` instead, or rely on the `load_dotenv()` calls now at the top of `main.py`/`app.py` having already run (true for anything imported after the app module, false for standalone scripts run directly — those still need their own `load_dotenv()` call, as `research_synthesizer.py`'s own `if __name__ == "__main__"` block and this session's manual test scripts did).

**Point-in-time correctness is universal and non-negotiable.** Every feature, every research synthesis, every regime label — a value computed "as of date d" may only read source rows with a date `<= d`.

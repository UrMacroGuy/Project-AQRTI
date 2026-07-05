# AQRTI — Improvements Backlog

*Working file: every known mistake, stale claim, or polish item found in the 2026-07-05 full documentation review lives here. Work is carried out FROM this file — pick an item, do it, check it off with the date, add a CHANGELOG entry, and sync PROJECT_DIARY.md per its §16 rule.*

**Review scope:** all 16 `plans/*.md`, `docs/*.md`, `README.md`, `AQRTI_USER_GUIDE.md`, `PROJECT_DIARY.md`, `DATABASE_AND_TRAINING.md`, `CHANGELOG.md` (through `2026-07-03f`), plus code verification of `ui/app.js`, `ui/api.js`, `backend/strategies/promotion_config.py`, and `backend/seed_missing_data.py`.

**Priority key:** P0 = violates a hard project rule, fix first · P1 = factually wrong user-facing docs · P2 = historical docs needing labeling · P3 = consistency/polish.

---

## P0 — Placeholder / fabricated data (hard rule: NEVER visible in this project)

The 2026-06-25 "Remove All Mock Data" session deleted the main `DataStore` mock object, but the review found placeholder data still live in three places:

- [x] **P0-1 — Purge fabricated DB rows from `earnings_events` and `options_chain`.** (done 2026-07-05)
  Confirmed the script HAD been run — purged 26 fabricated `EarningsEvent` rows and 1 fabricated `OptionsChain` row (matched exactly against the hardcoded seed dict). Verified live: `GET /api/v1/earnings/calendar` → `{"calendar":[]}`, `GET /api/v1/options-intelligence` → `{"status":"no_data"}`. Both honest.
- [x] **P0-2 — Delete or quarantine `backend/seed_missing_data.py`** (done 2026-07-05) — deleted entirely (git history preserves it).
- [x] **P0-3 — Remove `MOCK_AGENT_DATA` from `ui/app.js`** (done 2026-07-05) — removed the object and the `useMock` fallback block; `hydrateResearchOps` now uses real API data only, with the existing "No agents registered" / "No findings today" empty states the markup already supported.
- [x] **P0-4 — Remove `MOCK_VAULT_DATA` from `ui/app.js`** (done 2026-07-05) — removed the object and its fallback; `hydrateVault` now degrades to real empty arrays/objects, using the existing "No snapshots yet" style empty states.
- [x] **P0-5 — Strip the dead `USE_MOCK` plumbing.** (done 2026-07-05)
  Removed `API_CONFIG.USE_MOCK` from `api.js` and all 9 `if (API_CONFIG.USE_MOCK) return null;` guards in `app.js`, plus the stale `// They are no-ops when USE_MOCK = true` comment and the `app.js:3` header ("Phase 1: Complete UI Shell with Realistic Mock Data" → accurate description). Both files verified syntactically valid (`node -c`) after the edit.
- [x] **P0-6 — Full-project fabricated-data audit.** (done 2026-07-05)
  Ran a dedicated research pass across backend + UI. Found and fixed **two real violations beyond this list**:
  1. `data_supremacy/fii_dii_scraper.py`'s `_maybe_backfill_history()` wrote randomized (`random.uniform()`) but plausible-looking FII/DII crore flows into `fii_dii_flows` with no synthetic flag — indistinguishable from real scraped data. Deleted the function; purged all 44 existing rows (couldn't reliably separate real from fabricated given an exact match to the 30-day backfill window). Verified live: `GET /api/v1/fii-dii` now returns honest empty arrays.
  2. The Overview page's "Today's Alerts" panel (`ui/index.html`) had four alerts hardcoded directly into the HTML with **zero JS wiring at all** (not even a mock-fallback pattern — just permanently-fake dead HTML). Wired real hydration from the existing `/research-findings/summary` API instead, with an honest "No alerts today" empty state.
  Everything else the audit checked (AQRTINet's `np.random.seed` in its own smoke-test block, `regime_discovery.py`'s seeded K-means init, the index-futures `is_synthetic=True` segment, "synthetic equity curve" labels that are actually real trade aggregation) was confirmed legitimate — not a violation.

---

## P1 — Factually wrong or dangerously stale user-facing docs

- [x] **P1-1 — `README.md`: wrong ML stack.** (done 2026-07-05) Fixed both occurrences to CatBoost + NGBoost + AQRTINet v3.1.
- [x] **P1-2 — `README.md`: stale/inflated stats block.** (done 2026-07-05) Replaced with a dateless "Current State" paragraph explaining the Trust Overhaul, pointing to the live dashboard and `promotion_config.py` as sources of truth.
- [x] **P1-3 — `README.md`: architecture section.** (done 2026-07-05) Removed the DataStore-mock line; corrected family/mutation-op/fitness-dimension counts to 11/9/6 (verified against code, not assumed); replaced "45+ endpoints" with the actual count (265 across 59 route files, verified via grep).
- [x] **P1-4 — `README.md` + `AQRTI_USER_GUIDE.md`: strategy → algo naming pass.** (done 2026-07-05) Completed in both docs' user-facing prose; literal code/table/API-path identifiers (`backend/strategies/`, `GET /strategies`) left untouched.
- [x] **P1-5 — `AQRTI_USER_GUIDE.md`: wrong model list + stale header + facts.** (done 2026-07-05)
  Fixed models (CatBoost+NGBoost+AQRTINet), replaced the hardcoded header with a dateless dashboard pointer + Trust Overhaul explanation. Stop-loss glossary entry corrected to "per-algo DSL value, varies" (not a fixed 8%). Confidence-threshold claim: could NOT verify "50 since 2026-06-27" — `MIN_CONFIDENCE` in `backend/paper_trading/continuous_monitor.py` is still `60.0` in code today — so pointed the doc at the actual source constant instead of asserting an unverifiable number. Flagging this discrepancy rather than silently either keeping the old "60%" or trusting the backlog's "50" claim without evidence.
- [x] **P1-6 — `PROJECT_DIARY.md`: out of sync.** (done 2026-07-05) Added Timeline phase H + I, corrected §6 (MAX_DRAWDOWN_LIMIT -35%, arena_status isolation), added full AQRTINet v3.1 details to §5, added the index-futures parallel schema to §12, bumped "Last synced" to 2026-07-05 / through `2026-07-05c`.
- [x] **P1-7 — `docs/STRATEGY_ARENA.md`: constants out of sync with `promotion_config.py`.** (done 2026-07-05) Fixed §5 (backtest window 1095→1825d, liquidity filter), §7 (full gate table rewrite: MIN_BACKTEST_TRADES=60, MIN_SHARPE=0.5, added OOS/benchmark/duplicate/quarantine gates and the -35% drawdown retirement gate), §8 (BACKTEST_DAYS 1095→1825, added the bootstrap parent tier), §13 (constants table corrected + source-of-truth banner added at the section header, exact wording as requested).
- [x] **P1-8 — `docs/fix_backtest_division_by_zero.md`: close it out.** (done 2026-07-05) Added a "Status: OBSOLETE" resolution section — the code it investigates was entirely rewritten by the 2026-07-02 backtester rebuild (confirmed no traceback-logging patch remains in current `strategy_research_loop.py`, and `strategy_metrics.py`'s divide-by-std sites already guard `if std==0`). Marked unresolved-but-obsolete rather than falsely claiming proof, since the exact original failing line was never captured. Original notes kept below the resolution for historical reference.
- [x] **P1-9 — `DATABASE_AND_TRAINING.md`: minor sync.** (done 2026-07-05) Checked all the specific claims (dataset loader 2000 days, WF_TRAIN_YEARS=1.0, quarterly test windows, IC sample=10000, AQRTINet v3.1 details) against code — found the file already reflected all of them accurately (created/updated by a concurrent session earlier today). The one genuine gap was §11 missing the index-futures parallel schema entirely — added it.

---

## P2 — `plans/` folder: label the historical design docs

All 16 files in `plans/` are Version-1.0 aspirational design documents from the initial build. They contain numbers that are now wrong (promotion gates fitness≥20/trades≥8; 5-dimension fitness; 11 mutation ops; 7-8 families; LightGBM/XGBoost meta-layer; 9-page dashboard; "847 promoted strategies"). They are valuable as history but actively misleading if read as current documentation — especially `PROJECT_SUMMARY.md`, which is literally titled "Current State."

- [x] **P2-1 — Add a standard banner to every `plans/*.md`.** (done 2026-07-05) Added to all 17 files (one more than originally counted).
- [x] **P2-2 — `plans/PROJECT_SUMMARY.md`: retitle.** (done 2026-07-05) → "PROJECT AQRTI — State as of 2026-06-25 (historical)".
- [x] **P2-3 — `plans/MASTER_IMPLEMENTATION_ROADMAP.md`: refresh the phase-status table.** (done 2026-07-05) Rewrote the table (marked phases 3/5 "Done (superseded)" with what changed, added phases G/H for the Trust Overhaul + feature-fix work). Re-verified Known Gaps against live data: "Options Intelligence no_data" CONFIRMED still true today; "volatility_play 2% coverage" RESOLVED (now 131 strategies, 13% of population, verified via DB query); "ML biased Bearish/Neutral" neither confirmed nor refuted since the whole ensemble it described no longer exists — flagged as needing a fresh check. Added the real current gap: 0/927 promoted under the honest gates.

---

## P3 — Consistency & polish

- [ ] **P3-1 — Universe-number consistency.** Docs variously claim 779 / 641 / 639 / 608 symbols while backtests run on 352 active symbols. Pick the convention (total tracked vs. active-with-features vs. backtest-eligible-liquid) and state it once in PROJECT_DIARY §4; other docs reference the definition, not a raw number.
- [ ] **P3-2 — Stop hardcoding live stats in markdown.** Any doc that quotes population counts, fitness scores, or Intelligence Score must date-stamp them ("as of YYYY-MM-DD") or link to the dashboard. This review found five docs contradicting each other purely because each froze a different day's numbers.
- [ ] **P3-3 — `aqrtinet/README.md` (public repo) accuracy check** against the v3.1 push — public-facing claims should match the shipped model.
- [ ] **P3-4 — `docs/` vs `plans/` purpose statement.** Add a one-line README or note: `docs/` = current technical ground truth, `plans/` = historical design. New ground-truth docs go in `docs/` (or root, like the diary).
- [ ] **P3-5 — UI DNA-viewer input** (`index.html:1315`, `:1758`) still says "Enter strategy ID…" — rename to "algo ID" for consistency with the `ee57c8f` UI rename.

---

## P-PF — Personal Portfolio module (NEW — spec: `docs/PERSONAL_PORTFOLIO_PLAN.md`)

Track the user's real 60-40 investment plan (₹2,000/month, Zerodha + INDmoney) inside AQRTI with real data, fully separate from paper trading and the algo population. AQRTI tracks and advises — it never executes. Build in this order:

- [ ] **PF-1 — Instrument verification (blocks all other PF items).** Confirm with the user: exact gold ETF ticker (plan says "GOLDNXT" — unverified; don't guess, verify the instrument actually bought), and the exact AMFI scheme codes for the Nifty 50 and Smallcap 250 index funds once chosen on Coin. Verify PLTR/LMT have full 5yr `DailyPrice` + `FeatureValue` coverage (they're in `global_universe.py`; coverage unverified).
- [ ] **PF-2 — Schema:** 6 new tables per spec §4 (`PortfolioInstrument`, `PortfolioTransaction` (append-only/immutable), `PortfolioHolding` (derived), `PortfolioValuation`, `MutualFundNAV`, `PortfolioActionLog`) in `models.py` + idempotent migration script.
- [ ] **PF-3 — Data ingestion:** add VTI + verified gold ETF to `global_universe.py` with 5yr backfill + features; new AMFI NAV ingester (free public NAVAll feed) for the two mutual funds; USD/INR valuation path for US holdings. Every stored price/NAV carries source + date; MF values are always prior-day NAV and the UI must say so.
- [ ] **PF-4 — API + valuation engine:** `/api/v1/portfolio/*` routes; holdings derived from transactions; XIRR, 60/40 + risk-bucket drift (flag >5pp), tax-lot LTCG countdowns (24-month), Schedule FA reminder (Jul 31).
- [ ] **PF-5 — UI page #15 "My Portfolio":** header KPIs, allocation-vs-target, holdings table, monthly/quarterly plan checklist auto-generated from the plan (incl. Jan/Apr/Jul/Oct rotation: TCS→INFY→HDFCBANK→RELIANCE), projections-vs-actuals (projections labeled "plan assumption"), tax panel, read-only AQRTI intelligence overlay for the 6 tradeable single names. Honest empty state until first real transaction is recorded — no simulated holdings, ever.
- [ ] **PF-6 — Scheduler wiring:** daily post-close valuation snapshot (IN), US refresh after US close/next boot, action-reminder generation into `PortfolioActionLog`.
- [ ] **PF-7 — US algo segment:** `asset_class="us_portfolio"` track for PLTR/LMT/VTI following the index-futures isolation precedent — US cost model (~0.10%), no NSE circuit logic, benchmark gate vs buy-and-hold VTI (not NIFTY), never mixed with the NSE population. Mutual funds excluded from algo training (NAV has no microstructure). Add a per-algo "performance on portfolio names" evaluation view.

---

## P-OBS — Obsidian integration (spec: `docs/OBSIDIAN_INTEGRATION_PLAN.md`)

One-way exporter rendering DB knowledge into an Obsidian vault (`AQRTI Vault/` outside the repo, in OneDrive). DB stays source of truth; vault is derived/regenerable; exporter only ever overwrites files carrying `aqrti_generated: true`; no filler content for missing data.

- [x] **OBS-1 — Phase 1 core (done 2026-07-05):** `backend/obsidian/vault_exporter.py` + `renderers.py` + `vault_writer.py` — Daily / Stock / Lesson / Home notes (formats + frontmatter schemas per spec §3-4); `settings.obsidian_vault_path` config (disabled if unset, verified empty by default); idempotent byte-compare upserts; ownership check (`aqrti_generated: true` marker, verified a foreign file is never touched); wikilinks between days↔stocks↔lessons. Verified against the real DB: 1044 notes written on first run (5 daily, 304 stock, rest lessons+home), re-run reported 100% `unchanged` (idempotent), no filler content for missing knowledge_score. Not yet wired: scheduler step + admin endpoint + first-run backfill semantics are OBS-2.
- [x] **OBS-2 — Wiring (done 2026-07-05):** Added Step 13 (`obsidian/vault_exporter.export_vault(full=False)`) to `aqrti/data/scheduler.py`'s `_daily_job`, immediately after Step 12 (Historical Intelligence) and the existing Step 10 vault archive — wrapped in its own try/except so a failure logs and never blocks the rest of the pipeline (matches every other step's pattern). Added `POST /admin/obsidian-export?full=true` to `aqrti/api/app.py` (same async-to-thread pattern as `/admin/vault`/`/admin/data-supremacy`); verified live via `TestClient` against the real DB with a scratch vault path — 200 OK, 1044 notes written. First-run backfill is just `full=True` (`export_vault`'s `since = date(2000,1,1)` path already implemented in OBS-1) — no separate backfill mechanism needed since the exporter is already idempotent/full-history-capable.
- [ ] **OBS-3 — Phase 1.5:** Algo notes (promoted/active only, `status: retired` on demotion — never delete) + per-agent report notes.
- [ ] **OBS-4 — Phase 2:** Portfolio notes (plan, transactions, monthly checklist) — blocked on P-PF module existing.
- [ ] **OBS-5 — Phase 3 (deferred, needs own design before any work):** two-way vault-inbox → agent research tasks. Do not start without a written spec; reading user files needs parsing conventions + guardrails.

---

## P-ARCH — Architecture review findings (2026-07-05)

Whole-architecture review; these are structural, not cosmetic:

- [ ] **ARCH-1 — Stray database at project root.** `./aqrti.db` (101 MB) sits beside the real `backend/aqrti.db` (3.1 GB). Almost certainly a stale artifact from an old working-directory bug. Verify nothing opens it (grep connection strings / relative paths), then archive or delete — a second DB file is a data-integrity trap.
- [ ] **ARCH-2 — No test suite.** Zero automated tests for a system with money-grade correctness requirements; every past regression (fake Sharpe, leakage, poisoned session) was caught by manual audit. Start minimal and high-value: regression tests for `strategy_metrics` (honest Sharpe/Sortino/MDD on known series), `label_generator` (no backward label), `dataset_builder` (leak-guard: assert no `_x`/`_y` cols), promotion gates, and the session-rollback pattern. Run before backend restarts.
- [ ] **ARCH-3 — No migration framework.** Schema changes are ad-hoc scripts (`migrate_oos_and_cleanup.py` etc.). Adopt a lightweight convention: numbered idempotent scripts in `backend/scripts/migrations/` + a `schema_migrations` table recording what ran. (Full Alembic optional; the convention is the win.)
- [ ] **ARCH-4 — Scheduler and API share one process.** A heavy pipeline step can starve API responsiveness, and a crash takes both down (2026-07-03e killed everything). Consider splitting scheduler into its own process (same codebase, `python -m aqrti.scheduler`) so the dashboard stays alive during retrains/re-backtests. Also formalizes the DB single-writer story (ARCH-7).
- [ ] **ARCH-5 — `ui/app.js` is a ~5,000-line monolith.** All 14 (soon 15) page renderers + hydration in one file. No framework needed — just split into `ui/pages/*.js` modules loaded from `index.html`, one per page, keeping the existing patterns. Do this before adding the My Portfolio page rather than growing the monolith further.
- [ ] **ARCH-6 — `models.py` is a 2,300-line/93-table monolith.** Split into `database/models/` package by subsystem (market, features, ml, algo, paper, learning, agents, vault, supremacy, p9, futures, portfolio) re-exported from `__init__.py` so imports don't change. Low urgency, do opportunistically when PF-2 adds tables.
- [ ] **ARCH-7 — SQLite write contention is handled by convention only.** "database is locked" during concurrent script+backend runs is documented as expected. Set `busy_timeout` on all connections, keep WAL, and write the rule down: heavy bulk writes go through scripts run with the backend stopped, or through the scheduler process (after ARCH-4).
- [ ] **ARCH-8 — No API auth.** Fine while strictly localhost, but admin endpoints (`/admin/*` triggers, activate-algo) are unauthenticated; any future LAN/cloud exposure is a foot-gun. Minimum: bind explicitly to 127.0.0.1 (verify) + a simple token header on `/admin/*` and mutation routes.
- [ ] **ARCH-9 — Backup policy is manual.** `aqrti.db.bak-YYYYMMDD` copies exist ad hoc and vault "backups" are snapshots inside the same DB file. Add a weekly scheduler job: `sqlite3 .backup` to a separate folder (ideally another drive), keep last N, verify integrity (`PRAGMA integrity_check`) after copy. A single corrupted 3.1GB file currently loses everything.
- [ ] **ARCH-10 — Legacy dead tables.** `Trade`, `Mistake`, `Strategy` (v1), `ModelRecord`, `OptionsData` are superseded but still in the schema, inviting wrong queries (the Risk page once read empty `Trade`). Mark deprecated in `models.py` docstrings now; drop after confirming zero readers (grep) in a migration later.
- [ ] **ARCH-11 — Electron desktop build is stale.** Installers were built 2026-06-22, before the Bloomberg redesign, algo rename, and every subsequent UI change. Either rebuild on a cadence/after UI milestones, or de-emphasize the desktop app in docs until rebuilt (README currently presents it as current).
- [ ] **ARCH-12 — `FeatureValue` long-format scale.** 16.7M rows and growing ~150 rows per symbol-day; every dataset build pays a pivot. Not urgent (bulk upsert + shared cache already mitigate), but note the eventual path: wide per-(symbol,date) table or columnar sidecar (Parquet) for training reads, keeping SQLite as source of record. Decide only when training-build time actually hurts.

---

## How to work this file

1. Pick the highest-priority unchecked item (P0 first — the placeholder-data items are non-negotiable).
2. Do the work; verify with evidence (DB query, page render, grep), not assumption.
3. Check the box and append `(done YYYY-MM-DD)` to the item.
4. Add a CHANGELOG entry; sync `PROJECT_DIARY.md` per its §16 rule if the change alters described system state.
5. New problems discovered mid-work get added here as new items, not fixed silently.

*File created 2026-07-05 from a full-docs + targeted-code review. See CHANGELOG entry `[2026-07-05]`.*

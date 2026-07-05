# AQRTI — Improvements Backlog

*Working file: every known mistake, stale claim, or polish item found in the 2026-07-05 full documentation review lives here. Work is carried out FROM this file — pick an item, do it, check it off with the date, add a CHANGELOG entry, and sync PROJECT_DIARY.md per its §16 rule.*

**Review scope:** all 16 `plans/*.md`, `docs/*.md`, `README.md`, `AQRTI_USER_GUIDE.md`, `PROJECT_DIARY.md`, `DATABASE_AND_TRAINING.md`, `CHANGELOG.md` (through `2026-07-03f`), plus code verification of `ui/app.js`, `ui/api.js`, `backend/strategies/promotion_config.py`, and `backend/seed_missing_data.py`.

**Priority key:** P0 = violates a hard project rule, fix first · P1 = factually wrong user-facing docs · P2 = historical docs needing labeling · P3 = consistency/polish.

---

## P0 — Placeholder / fabricated data (hard rule: NEVER visible in this project)

The 2026-06-25 "Remove All Mock Data" session deleted the main `DataStore` mock object, but the review found placeholder data still live in three places:

- [ ] **P0-1 — Purge fabricated DB rows from `earnings_events` and `options_chain`.**
  `backend/seed_missing_data.py` (docstring: *"Seed earnings_events and options_chain with computed/estimated data since NSE scraping is blocked (403). Run once to populate these tables so the UI shows data."*) wrote **invented earnings figures** (hardcoded rev/PAT/EPS presented as actuals, `random.uniform()` YoY growth, fabricated BEAT/MISS verdicts) and **random options data** (`pcr = random.uniform(0.75, 1.25)`, random max pain, random IV skew) into the database. If this script was ever run, the Data Intelligence page is showing random numbers as real market data.
  **Do:** query both tables for seeded rows (the 18 hardcoded symbols × the hardcoded dates identify them), delete them, and verify the Data Intelligence page shows an honest "NO DATA — source unavailable" state instead.
- [ ] **P0-2 — Delete or quarantine `backend/seed_missing_data.py`** so it can never be run again. If the NSE 403 block is the real problem, the fix is a working scraper or an honest empty state — never synthesized rows. (Contrast with the index-futures cost-of-carry series, which is acceptable because every row is flagged `is_synthetic=True` and labeled in the UI — the rule is: synthetic data must be impossible to mistake for real data.)
- [ ] **P0-3 — Remove `MOCK_AGENT_DATA` from `ui/app.js` (line ~2819).**
  When the agents API returns nothing, the Research Ops page silently renders 5 fake agents, a fake daily brief, fake findings, and fake messages as if real (`useMock = !agentData` at line ~2864, plus the `mockFindings` fallback at ~2949-2950). Replace with an explicit offline/empty state ("BACKEND OFFLINE — no agent data").
- [ ] **P0-4 — Remove `MOCK_VAULT_DATA` from `ui/app.js` (line ~3163).**
  Same pattern on the Intelligence Vault page (~3205-3210): fake snapshots/knowledge/portfolio/research/backups rendered when the API fails. Same fix: honest empty state.
- [ ] **P0-5 — Strip the dead `USE_MOCK` plumbing.**
  `ui/api.js:8` (`USE_MOCK: false`) plus ~10 `if (API_CONFIG.USE_MOCK) return null;` guards in `app.js` are dead code that keeps the door open for mock modes. Remove the flag and guards entirely. Also fix the stale header comment `ui/app.js:3` ("Complete UI Shell with Realistic Mock Data") which misdescribes the file.
  *(Note: HTML `placeholder=` attributes on inputs, e.g. `index.html:232`, are fine — those are UX hints in empty form fields, not fabricated data.)*
- [ ] **P0-6 — Full-project fabricated-data audit.** After P0-1..5, grep backend + UI for any remaining `random.uniform|random.gauss|fake|sample_data|hardcoded` values that flow into user-visible numbers, and confirm every page shows an explicit empty/error state when its API has no data. Rule of thumb: any number the user sees must trace to a DB row that traces to a real source (or be clearly labeled synthetic/estimate).

---

## P1 — Factually wrong or dangerously stale user-facing docs

- [ ] **P1-1 — `README.md`: wrong ML stack.** Lines 122 and 314 list "CatBoost, LightGBM, XGBoost" — LightGBM/XGBoost were removed 2026-06-27 (sub-coin-flip accuracy). Current stack: CatBoost + NGBoost + AQRTINet v3.1.
- [ ] **P1-2 — `README.md`: stale/inflated stats block** ("Current Stats 2026-06-28": 7,000+ strategies, best fitness 69.8, Intelligence Score 71.5). These predate the Trust Overhaul; the honest state (2026-07-03d) is a 927-algo population with **0 promoted** — no algo has yet proven an edge under the honest backtester. **Do:** replace the hardcoded stats table with a short honest paragraph + "see the live dashboard for current numbers," so the README can't silently rot again.
- [ ] **P1-3 — `README.md`: architecture section still says** "DataStore → Fallback mock data (mirrors API schemas)" — the mock DataStore was deleted 2026-06-25. Also update "45+ REST API endpoints" (now 50+) and the strategy-evolution bullet ("8 families, 11 mutation ops, 5-dimension fitness" → 10/11 families, 9 mutation ops, 6-dimension fitness).
- [ ] **P1-4 — `README.md` + `AQRTI_USER_GUIDE.md`: strategy → algo naming pass** in user-facing prose, matching the UI rename (commit `ee57c8f`). Keep literal code/table identifiers as-is.
- [ ] **P1-5 — `AQRTI_USER_GUIDE.md`: wrong model list** (line 117: "CatBoost, LightGBM, XGBoost") and stale header state (line 5: "Intelligence Score 71.5 · 4,087 strategies · 847 promoted"). Update models, and replace the header snapshot with a dateless pointer to the dashboard. Also fix: glossary's "Stop Loss (default: 8% below entry)" (SL is now per-algo DSL, typically 4-9%), and the paper-trading minimum confidence (doc says 60%, default has been 50 since 2026-06-27). Add a short "2026-07 Trust Overhaul" note explaining why historical stats reset — a reader comparing old screenshots to today's dashboard deserves the explanation.
- [ ] **P1-6 — `PROJECT_DIARY.md`: out of sync.** Last synced `2026-07-02b`; CHANGELOG now has six newer entries (`2026-07-03` a–f). Fold in, per the diary's own §16 rule:
  - New timeline phase row **H (2026-07-03)**: feature-coverage fix (1200→2000 days), arena OOS/robustness gates, meta-learner shrinkage, AQRTINet v3.1, population cleanup (1,229 zero-trade algos deleted) → honest baseline of **0 promoted / 927 population**, evolution bootstrap parent tier, orphaned-position crash fix, index-futures segment foundation.
  - §6 corrections: `MAX_DRAWDOWN_LIMIT` is now **−35%** on honest MTM drawdown (diary still says the MDD gate was "removed entirely / set to −100%"); backtest window 1825d; add the `arena_status` column separation and the index-futures `asset_class` isolation.
  - §5: AQRTINet v3 → v3.1 details (9 interaction features, 252d half-life, 7-fold stacking, 5-fold Platt, confident-label 0.3× weighting).
  - §12: new tables (`IndexFuturesContract` + parallel futures tables).
  - Bump the "Last synced" line.
- [ ] **P1-7 — `docs/STRATEGY_ARENA.md`: constants out of sync with `promotion_config.py`.** §7/§13 still say MIN_TRADES 300, MIN_SHARPE 0.3, BACKTEST_DAYS 1095, and omit the benchmark gate (0.8× NIFTY Sharpe), duplicate gate (0.60 Jaccard), quarantine gates (60d/20 trades/50% WR), and `MAX_DRAWDOWN_LIMIT −35`. **Do:** update the numbers AND add a banner at the top of §13: "Gate constants live in `backend/strategies/promotion_config.py` — that file is the single source of truth; if this doc disagrees, the config wins."
- [ ] **P1-8 — `docs/fix_backtest_division_by_zero.md`: close it out.** It's an open-ended live investigation doc with no resolution recorded. Append a resolution section (the division-by-zero class of bugs was superseded/resolved by the 2026-07-02 backtester rebuild) or explicitly mark it unresolved-but-obsolete. An investigation doc without an ending is a trap for future readers.
- [ ] **P1-9 — `DATABASE_AND_TRAINING.md`: minor sync.** Update for v3.1 pipeline calibrations (dataset loader 1500→2000 days, WF_TRAIN_YEARS 1.0, quarterly folds, IC sample 10000) and add the index-futures parallel schema to §11. Small, but this doc claims to be code-verified so it should track code.

---

## P2 — `plans/` folder: label the historical design docs

All 16 files in `plans/` are Version-1.0 aspirational design documents from the initial build. They contain numbers that are now wrong (promotion gates fitness≥20/trades≥8; 5-dimension fitness; 11 mutation ops; 7-8 families; LightGBM/XGBoost meta-layer; 9-page dashboard; "847 promoted strategies"). They are valuable as history but actively misleading if read as current documentation — especially `PROJECT_SUMMARY.md`, which is literally titled "Current State."

- [ ] **P2-1 — Add a standard banner to every `plans/*.md`:**
  > ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).
  *(Chosen over moving files to `plans/archive/` — cheaper, preserves links, same effect.)*
- [ ] **P2-2 — `plans/PROJECT_SUMMARY.md`: retitle.** "PROJECT AQRTI — Current State" → "PROJECT AQRTI — State as of 2026-06-25 (historical)". This one file causes the most confusion because its title claims currency.
- [ ] **P2-3 — `plans/MASTER_IMPLEMENTATION_ROADMAP.md`: refresh the phase-status table only** (it's the one plans doc people actually consult). Phase 9 criteria should reference the current honest gates (promotion_config values + quarantine), and the "Known Issues" list needs re-verification — e.g. "ML model outputs mostly Bearish/Neutral" and "Options Intelligence no_data" may be stale or (per P0-1) worse than stale.

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

- [ ] **OBS-1 — Phase 1 core:** `backend/obsidian/vault_exporter.py` + renderers for Daily / Stock / Lesson / Home notes (formats + frontmatter schemas in spec §3-4); `settings.obsidian_vault_path` config (disabled if unset); idempotent byte-compare upserts; ownership check; wikilinks between days↔stocks↔lessons.
- [ ] **OBS-2 — Wiring:** daily scheduler step (after vault archive) + `POST /admin/obsidian-export?full=true`; failure-isolated like other steps; first-run backfill from all existing `ResearchBrief`/`LessonLearned` history with DB timestamps.
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

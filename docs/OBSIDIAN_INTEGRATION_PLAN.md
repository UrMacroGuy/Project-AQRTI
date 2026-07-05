# Obsidian Integration — Design Plan

*Planning document (no code yet). Defines how AQRTI exports its knowledge as a structured Obsidian vault — what gets written, where, in what format, and how the pieces connect. Work items live in `IMPROVEMENTS.md` §P-OBS; this doc is the spec they implement against.*

Created 2026-07-05. Status: **PLANNED — not yet built.**

---

## 1. The core idea

Obsidian is a viewer over a folder of plain markdown files — there is no "Obsidian API" needed for this. The integration is a **one-way exporter**: a new module (`backend/obsidian/vault_exporter.py`) that renders rows from the AQRTI database into markdown notes inside a vault folder. Obsidian opens that folder; its graph view, backlinks, search, and Dataview queries then work on AQRTI's knowledge automatically.

```
                    ┌──────────────────────────────────────────┐
   aqrti.db          │  backend/obsidian/vault_exporter.py     │        AQRTI Vault/
  (source of truth)  │                                          │      (derived, regenerable)
                     │  reads: ResearchBrief, LessonLearned,    │
  ResearchBrief ────►│  Prediction, PaperTrade, StrategyV2,     │────►  Daily/2026-07-05.md
  LessonLearned ────►│  KnowledgeScore, MarketRegime,           │────►  Stocks/TCS.md
  Prediction ───────►│  SentimentRecord, Portfolio* (later)     │────►  Lessons/L-0042 ….md
  PaperTrade ───────►│                                          │────►  Algos/AQRTI_STR_xxx.md
  StrategyV2 ───────►│  writes: markdown + YAML frontmatter     │────►  Portfolio/…  (phase 2)
                     │  + [[wikilinks]] connecting notes        │
                     └──────────────────────────────────────────┘
                              runs as daily scheduler step
                              + POST /admin/obsidian-export
```

**Direction of truth (non-negotiable):**
- The database is the source of record. The vault is a **derived view** — every note can be deleted and fully regenerated from the DB at any time.
- One-way only in phase 1: AQRTI writes, never reads, the vault. The user can annotate freely in their *own* notes that link to AQRTI's notes; AQRTI never touches user-authored files.
- Notes render only what exists in the DB. A day with no brief gets no daily note (or an explicit "no pipeline run this day" stub) — never filler content. Same no-placeholder rule as everywhere else.

## 2. Vault location & layout

Default vault path: **`C:\Users\praty\OneDrive\Desktop\AQRTI Vault\`** — *outside* the git repo (it's regenerated content, not source), inside OneDrive so Obsidian mobile can sync it. Configurable via `settings.obsidian_vault_path`; export disabled entirely if unset.

```
AQRTI Vault/
├── Home.md                     ← dashboard note: links to latest daily, top lessons, promoted algos
├── Daily/
│   └── 2026-07-05.md           ← one per pipeline day (the CRO brief + day summary)
├── Stocks/
│   └── TCS.md                  ← one per symbol that ever appears in a brief/trade/lesson
├── Lessons/
│   └── L-0042 Overconfidence in VOLATILE.md
├── Algos/
│   └── AQRTI_STR_A1B2C3D4.md   ← promoted/active algos only (not all 927)
├── Reports/
│   └── 2026-07-05 Market Research.md   ← per-agent reports (optional, phase 1.5)
├── Portfolio/                  ← phase 2, after the My Portfolio module exists
│   ├── Plan.md
│   └── Transactions/2026-08-01 VTI buy.md
└── _meta/
    └── export_log.md           ← when the exporter last ran, counts, errors
```

Every AQRTI-generated file carries `aqrti_generated: true` in frontmatter — that flag is the exporter's ownership marker: it will only ever overwrite files carrying it, so a user-created note can never be clobbered even if it collides on name.

## 3. Note formats — exact content per type

### 3.1 Daily note — `Daily/YYYY-MM-DD.md`
Source tables: `ResearchBrief` (the CRO brief for that date), `KnowledgeScore`, `MarketRegime`, `Prediction` (top 5 by confidence), `PaperTrade` (opened/closed that day).

```markdown
---
aqrti_generated: true
type: daily
date: 2026-07-05
regime: SIDEWAYS
knowledge_score: 71.5
trades_opened: 2
trades_closed: 1
tags: [aqrti/daily]
---

# AQRTI Daily — 2026-07-05

## Market summary
{ResearchBrief.market_summary}

## Top opportunities
- [[RELIANCE]] — Bullish, 78% confidence, +2.1% expected   ← from Prediction rows
...

## Trades
- Opened: [[TCS]] ×4 @ ₹4,120 (algo [[AQRTI_STR_A1B2C3D4]])
- Closed: [[INFY]] +3.2% (target hit)

## Risks / Lessons today
- [[L-0042 Overconfidence in VOLATILE]]

## Action items
{ResearchBrief.action_items}
```

Every symbol is a `[[wikilink]]` → backlinks on the stock note; every lesson/algo mention links too. This is what makes the graph view meaningful: days connect to stocks connect to lessons connect to algos.

### 3.2 Stock note — `Stocks/SYMBOL.md`
Source: `Stock`, latest `Prediction`, `SentimentRecord`, open `PaperPosition`, `PaperTrade` history for the symbol. Created lazily — only for symbols that actually appear in a brief, trade, lesson, or the personal portfolio (not all 779).

Frontmatter: `type: stock, symbol, sector, exchange, last_prediction, last_confidence, sentiment_score, in_portfolio: true/false`. Body: current AQRTI view (2-3 lines), open position if any, last 10 trades table. The **backlinks panel** then automatically shows every daily note and lesson that ever mentioned the stock — that's the integration's biggest payoff and it costs nothing.

### 3.3 Lesson note — `Lessons/L-#### {title}.md`
Source: `LessonLearned` (+ its `FailureRecord`). Frontmatter: `type: lesson, category, severity, regime, applied: true/false, date`. Body: what happened / why / recommendation, linking `[[SYMBOL]]` and `[[Daily/YYYY-MM-DD]]`. Lessons are AQRTI's most human-readable output; in Obsidian they become a browsable, queryable mistake journal.

### 3.4 Algo note — `Algos/{strategy_id}.md`
Source: `StrategyV2` — **promoted/active only** (a note per all 927 candidates would be graph noise). Frontmatter: `type: algo, family, status, fitness, sharpe, win_rate, oos_passed, promoted_at`. Body: plain-English rendering of the DSL entry rules, gate results, shadow-trade record. Retired algos get `status: retired` on next export rather than deletion (history preserved).

### 3.5 Home note — `Home.md`
Regenerated each export: link to today's daily, quick-jump links to all four index notes (§4.1), knowledge score trend (last 7 values, static + a live Dataview table of the last 10), currently promoted algos (or an honest "none yet" note explaining the gate chain when empty — never a blank section), 5 most recent lessons, portfolio month-checklist status (phase 2). Set as the vault's default landing page in Obsidian settings.

## 4. Frontmatter = Dataview database

The YAML frontmatter is deliberately uniform so the **Dataview** community plugin can query the vault like a database, entirely inside Obsidian, with zero extra AQRTI work:

```dataview
TABLE regime, knowledge_score FROM "Daily" WHERE knowledge_score < 60 SORT date DESC
TABLE severity, category FROM "Lessons" WHERE regime = "VOLATILE"
TABLE fitness, sharpe, win_rate FROM "Algos" WHERE status = "promoted" SORT fitness DESC
```

Tag scheme: everything under a single `aqrti/` namespace (`aqrti/daily`, `aqrti/lesson`, `aqrti/algo`, `aqrti/stock`, `aqrti/report`, `aqrti/home`, `aqrti/index`) so AQRTI content is one click to isolate or filter out in the graph.

### 4.1 Index notes — turning folders into sorted views
Each of `Daily/`, `Stocks/`, `Lessons/`, `Algos/` gets a `_index.md` (underscore-prefixed to sort first in the file explorer) containing a Dataview `TABLE` query scoped to that folder — e.g. `Algos/_index.md` lists every algo sorted by fitness, `Lessons/_index.md` sorts by severity then date. These are pure organization: no new DB reads, just a saved query over frontmatter that already exists. `Home.md` links to all four and embeds a live 10-row knowledge-score trend table. If Dataview isn't installed, the query renders as an inert fenced code block — the page still reads fine, just without the live table.

### 4.2 Presentation — Dataview install + visual theming
Because the plugin isn't just config (Obsidian needs its actual `main.js`/`manifest.json` present), the exporter setup includes shipping Dataview directly into the vault's `.obsidian/plugins/dataview/` folder pre-enabled (DataviewJS explicitly left **off** — only declarative `TABLE`/`LIST` queries are used, no arbitrary code execution), plus a CSS snippet (`.obsidian/snippets/aqrti-theme.css`, enabled by default) that color-codes each `aqrti/*` tag (daily=blue, stock=grey, lesson=orange, algo=green, report=purple, home=gold) in tag pills, the file explorer, and the graph view's color groups (`graph.json`). This is a one-time setup written alongside the vault's first export, not something the exporter re-writes on every run — `.obsidian/` is Obsidian's own config, untouched by `vault_exporter.py`.

## 5. Exporter mechanics

- **Module**: `backend/obsidian/vault_exporter.py` + small per-type renderers. Pure read-DB → write-files; no DB writes except an `export_log` line (and none in phase 1 — the log is a vault file).
- **Idempotent upserts**: each note is deterministically rendered from DB state and overwritten in full if changed (compare rendered bytes → skip unchanged files, so OneDrive isn't churned daily). Ownership check first: refuse to overwrite any file lacking `aqrti_generated: true`, log the collision.
- **Scheduling**: runs as a late step of the daily 15:30 IST pipeline (after the vault-archive step, so briefs/lessons/scores for the day exist), plus manual trigger `POST /admin/obsidian-export?full=true` (full = regenerate everything; default = today + touched notes).
- **First run**: backfills from existing history — every `ResearchBrief`, all lessons, promoted algos, plus stock notes for anything referenced. All timestamps come from the DB rows, so the backfilled vault reads as if it had always existed.
- **Failure isolation**: wrapped like every scheduler step — an export failure logs and never blocks the pipeline. Vault missing/unwritable → skip with one warning, not a crash.
- **Deletes**: the exporter never deletes files. Obsolete notes get `status: stale` frontmatter on full export. (A `--prune` flag on the manual endpoint may hard-delete `aqrti_generated` files later; not in phase 1.)

## 6. What is explicitly NOT in this integration

- **No reading the vault** (phase 1). Two-way — e.g. writing "watch TATASTEEL" in a note and having an agent pick it up — is a phase-3 idea requiring parsing conventions and guardrails; recorded in IMPROVEMENTS.md as a deferred item, not designed here.
- **No Obsidian Local REST API plugin, no plugins required at all.** The vault works with stock Obsidian; Dataview is optional sugar. Nothing depends on Obsidian even being installed — AQRTI just writes markdown.
- **No sync/conflict handling** beyond the ownership flag. OneDrive handles file sync; the exporter's skip-unchanged-files rule keeps churn minimal.
- **No secrets/credentials in notes.** Notes contain only what the dashboard already shows.

## 7. Phases (mirrors IMPROVEMENTS.md §P-OBS)

1. **Phase 1 — core vault**: exporter module + Daily, Stock, Lesson, Home notes; scheduler step + admin endpoint; first-run backfill; ownership/idempotency rules. This alone delivers the graph + backlinks + Dataview value.
2. **Phase 1.5 — algo & report notes**: Algos/ for promoted algos, Reports/ per-agent reports.
3. **Phase 2 — portfolio notes**: after the My Portfolio module (see `PERSONAL_PORTFOLIO_PLAN.md`) exists — plan note, transaction notes, monthly checklist state.
4. **Phase 3 (deferred, needs its own design)**: two-way — vault inbox notes parsed into agent research tasks.

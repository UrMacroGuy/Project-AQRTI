# UI_SPEC.md — Design spec for Markov Regime & Go/No-Go pages (+ shared tokens)

Companion to `docs/RESEARCH_DRIVEN_REARCHITECTURE.md` §7. The Cockpit is already card-based; these two pages are currently unstyled browser-default text with raw buttons (see 2026-07-11 screenshots) and need to be brought up to the same standard. Everything here uses the shared tokens in §0 — no page-local colors or font sizes.

## 0. Shared design tokens (applies to every page)

- **Type:** numbers/data in the existing monospace; labels and prose in the system sans stack (`-apple-system, Segoe UI, Roboto, sans-serif`). Minimum body size 13px, data values 14-15px, page titles 18-20px. ALL-CAPS reserved for nav-group labels and small badges only.
- **Contrast:** muted text no darker than `#8a919e` on the `#0d1117`-class card background (WCAG AA). The dimmest grey is metadata only (timestamps, source names).
- **Colour semantics (one meaning each):** green = positive/pass/owned · red = negative/fail/alert · amber = warning/stale/pending · one accent (existing orange) = interactive only. One badge component, one pill shape, everywhere.
- **Cards:** every content block lives in a card — `border: 1px solid #1f2530; border-radius: 6px; padding: 16-20px`, section title inside the card, not floating above it.
- **Buttons:** never browser-default. Accent-bordered ghost buttons (`transparent bg, 1px accent border, accent text, 4px radius, 6px 14px padding`), filled accent for primary actions.
- **States:** every panel resolves to exactly one of: data · "Backend offline" · honest empty ("No X yet — <reason>"). "Loading…" must never survive hydration.

## 1. Markov Regime page (`ui/pages/markov.js`)

Currently: raw text dump, default buttons, an unstyled table header with "Not generated yet…". Target layout — two-column grid (stack on narrow):

**Row 1 — hero: current regime.**
- Left card, "OBSERVABLE CHAIN (3-STATE)": a large regime badge dominating the card — `SIDEWAYS` in amber (BULL green / BEAR red), date beneath in muted mono. Below it, **regime bias as a horizontal diverging bar** (-1 Bear ←→ +1 Bull, marker at 0.041) instead of a bare number, and **persistence as a small meter** (96.1% = "sticky regime" label). Numbers keep their raw values next to the visuals — visuals aid, never replace, the data.
- Right card, "HIDDEN MARKOV MODEL": decoded regime class as a badge (`CLASS 0` + its mapped label if available), confidence as a slim progress bar with the % beside it, fit date + n_states + BIC-selected note in muted metadata. If HMM data missing: honest empty state, not a blank card.

**Row 2 — transition matrix card (new, data already exists in the module):** 3×3 grid heatmap of the observable transition matrix — rows "from", columns "to", cell shading by probability, exact values in each cell. This is the single most informative Markov artifact and it's currently not shown at all.

**Row 3 — watchlist card:** current watchlist as removable chips (symbol + ×), input + Add button styled per tokens. Empty state: "No symbols on the Markov watchlist yet".

**Row 4 — candidate strategies card:** the generate form (symbol input pre-filled from the curated universe as a dropdown, not free text — the universe is fixed) + results table styled like the Cockpit tables: proper column alignment (numeric right-aligned), family as a badge, Sharpe/win-rate colored by sign, honest empty state "Not generated yet — pick a symbol and Generate".

Keep the existing subtitle disclaimer ("standalone module — not eligible for promotion or paper trading") as an amber info-strip at the top, styled like the Cockpit's disclaimer banner.

## 2. Go/No-Go page (`gonogo` panels in `ui/core.js` / `ui/index.html`)

Currently: floating headings on empty space, everything stuck on "Loading…" (see FIX.md §4 — fix the data layer first, then this). Target layout:

**Row 1 — Morning Decision hero card:** full-width. Big verdict line (e.g. "NO-GO — no promoted algos yet") with a green GO / red NO-GO badge, then the "why" as 1-2 sentences of prose. This is the page's answer to "what should I do today" — it must read in 3 seconds.

**Row 2 — Readiness Scorecard card:** the 5 conditions as horizontal rows, each: condition name · current value vs required threshold in mono · a green PASS / red FAIL / amber PENDING pill. A summary strip on top: "2 of 5 green". Never render an empty region — if the endpoint fails, the whole card shows the offline state.

**Row 3 — two columns:**
- **Quarantine Progress:** per-candidate progress bars (days served / 60, trades closed / 20, WR vs 50%) once candidates exist; current honest empty state text stays but inside a proper card.
- **Today's Actionable Signals:** table of live signals from promoted algos (symbol, template, direction, entry zone, stop) — empty state as today, in-card.

**Row 4 — two columns:**
- **30-Day Pipeline Uptime:** compact calendar strip (30 squares, green/amber/red per day) + uptime % — replaces the bare "Loading…" text.
- **Monthly Review + Real-Capital Risk Rails:** merged into one card — review summary prose on top, risk rails as labeled key-value rows (max position size, monthly budget, drawdown halt threshold) in mono.

## 3. Acceptance checklist (both pages)

- Zero browser-default-styled elements (buttons, inputs, tables).
- Zero mojibake (`grep -c "â€"` on every touched file = 0 — see FIX.md §5).
- Every panel reaches data / offline / honest-empty within one hydration cycle; no permanent "Loading…".
- All text ≥13px; passes a squint test at 100% zoom on 1080p.
- Regime/verdict readable in under 3 seconds from page open (the hero cards carry the answer, details below the fold).
- No new data invented for visuals: every gauge/heatmap/bar renders values already returned by the existing `/api/v1/markov/*` and gonogo endpoints, with honest gaps where a field is missing.

// ui/app.js — STUB (ARCH-5 app.js split, 2026-07-05/06)
//
// This 6,533-line monolith was split into ui/core.js (shared/cross-cutting
// code: chart registry, helpers, nav, session, command palette, GO bar,
// pipeline health/watchdog, topbar live polling, boot sequence, both
// renderPage() definitions, Api.* extensions, the strategy-trades modal,
// the gonogo hydrate functions) plus one file per page under ui/pages/.
//
// 2026-07-11: screener.js deleted (pointless over a fixed 9-symbol curated
// universe); news.js + sentiment.js merged into one "Research" page; a new
// cockpit.js landing page was added.
// 2026-07-11 (UI revamp, §7 of the re-architecture plan): mojibake repair
// across ui/; retired ML prediction badges + degenerate SIP tilt table off
// Cockpit; readability/contrast/spacing pass in style.css; nav collapsed to
// ~10 tabs in 4 groups (COCKPIT/RESEARCH/ENGINE/CONTROL). Deleted pages
// (built for the old ~950-symbol universe, redundant against the 12-symbol
// Cockpit): overview.js, opportunity.js, live-prices.js, model.js,
// learning.js, vault.js, data-intelligence.js, intelligence-lab.js.
// Surviving pages: cockpit, market, analytics, news (Research), agents,
// strategy (Algos), arena, gonogo, markov, paper, risk. See CHANGELOG for
// full detail.
//
// ui/index.html now loads api.js, then core.js, then every ui/pages/*.js
// file directly via classic <script> tags (no bundler, no ES modules —
// still one shared global `window` scope, same as before the split).
//
// This file is intentionally left as an empty stub (not deleted) so any
// stale reference to "app.js" fails loudly instead of silently resolving
// to nothing. Do not add code here — add it to core.js or the relevant
// ui/pages/*.js file instead.

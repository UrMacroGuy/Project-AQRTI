// ui/app.js — STUB (ARCH-5 app.js split, 2026-07-05/06)
//
// This 6,533-line monolith was split into ui/core.js (shared/cross-cutting
// code: chart registry, helpers, nav, session, command palette, GO bar,
// pipeline health/watchdog, topbar live polling, boot sequence, both
// renderPage() definitions, Api.* extensions, the strategy-trades modal,
// the gonogo hydrate functions) plus one file per page under ui/pages/
// (overview, market, opportunity, news, sentiment, strategy, model,
// learning, risk, paper, agents, vault, data-intelligence, live-prices,
// intelligence-lab, analytics, screener, arena, strategy-trades-modal).
//
// ui/index.html now loads api.js, then core.js, then every ui/pages/*.js
// file directly via classic <script> tags (no bundler, no ES modules —
// still one shared global `window` scope, same as before the split).
//
// This file is intentionally left as an empty stub (not deleted) so any
// stale reference to "app.js" fails loudly instead of silently resolving
// to nothing. Do not add code here — add it to core.js or the relevant
// ui/pages/*.js file instead.

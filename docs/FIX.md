# FIX.md — Verified root causes for current UI data gaps (2026-07-11)

Every item below was diagnosed read-only against the live DB and source; nothing here is guesswork. Fix in this order.

## 1. Cockpit shows "NO DATA — source unavailable" for BEL, NTPC, CDSL, DRREDDY, LT, HAL (and VOO/QQQ)

**The data is NOT missing.** Verified directly in `aqrti.db`: all 9 Indian symbols have full `daily_prices` history through 2026-07-10 (BEL 1246 rows, NTPC 1246, CDSL 743, DRREDDY 1246, HAL 788, LT 1246, plus the 3 that work).

**Root cause:** `_NSE_STOCKS_MAP` in `backend/aqrti/api/routes/market.py` (~line 271) is a stale hardcoded dict from the OLD 950-symbol era: RELIANCE, TCS, AXISBANK, SBIN, BAJFINANCE, MARUTI, TITAN, WIPRO, ONGC, SUNPHARMA, NESTLEIND… Its only overlap with the new curated universe is HDFCBANK, ICICIBANK, INFY — exactly the 3 cards that show prices. The `/stocks` live-price endpoint only fetches symbols in this map (yfinance parallel fetch, with `_latest_stock_quote()` DB fallback), so the other 6+2 are never even attempted.

**Fix:**
1. Replace `_NSE_STOCKS_MAP` with the curated universe (single-source it from `settings.universe` rather than re-hardcoding — CLAUDE.md hard rule 4):
   `BEL.NS, HDFCBANK.NS, NTPC.NS, ICICIBANK.NS, INFY.NS, CDSL.NS, DRREDDY.NS, LT.NS, HAL.NS`, plus `VOO` and `QQQ` (plain US tickers — yfinance supports them directly, so the "US price feed pending" state can actually be retired).
2. The DB fallback (`_latest_stock_quote`) already exists and works — once the symbols are in the map, even a yfinance outage degrades to last-close-from-DB instead of NO DATA.
3. Keep the honest NO DATA state only for genuine total failure (no live quote AND no DB row).

## 2. Topbar tickers NIFTY/BNKN/VIX/USDINR stuck at "——"

`/live` (`get_live_prices`, market.py ~line 318) fetches `_LIVE_INDEX_MAP` via yfinance with **no DB fallback** — when yfinance fails or the market is closed and the fetch returns None, the topbar gets nothing. Fix: mirror the `/stocks` pattern — fall back to the latest `index_data` row per index (NIFTY history exists in DB; it drives the whole Markov module). Label fallback values as last close, not live.

## 3. Research synthesis exists for only 3 of 11 symbols

Verified: `research_synthesis` table has rows only for HDFCBANK (2), ICICIBANK (1), INFY (1). The cards' "NO DATA — no research synthesis yet" for the rest is HONEST (correct behavior, not a display bug). Causes to address:
1. The synthesizer has only been run against symbols that already had classified news events. Run the full-universe synthesis pass (all 9 NSE symbols) and wire it into the daily scheduler so coverage accumulates.
2. Verify `entity_extractor.py` maps news mentions to the new symbols (BEL/"Bharat Electronics", HAL/"Hindustan Aeronautics", LT/"L&T"/"Larsen", DRREDDY/"Dr Reddy's" name variants) — if entity mapping misses these aliases, their news never becomes symbol-tagged events and synthesis stays empty forever.
3. VOO/QQQ will never have NSE filings/news — their cards should say "US ETF — synthesis not applicable" rather than implying it's coming.

## 4. Go/No-Go page panels stuck on "Loading…"

`hydrateGoNogo()` and siblings in `ui/core.js` (~line 535) swallow errors (`catch (_) {}`) and only some panels render an offline state on null — "Morning Decision", "Scorecard", "30-Day Pipeline Uptime", "Monthly Review", and "Real-Capital Risk Rails" can stay on their initial "Loading…" text forever if their endpoint fails. Two-part fix:
1. Backend: hit each Go/No-Go endpoint (`Api.goNogo()`, `goNogoUptimeLog()`, morning-briefing, monthly-review) with the backend running and check for 500s — post-prune, queries touching truncated tables (old strategies/predictions) are the likely breakage.
2. Frontend: apply the established GO-9 pattern — every panel must resolve to exactly one of: data / "Backend offline" / honest empty state ("no promoted algos yet"). No panel may remain on "Loading…" after hydration completes.

## 5. Mojibake (`â€"`, `Â·`, `âœ…`, `âŸ³`) — confirmed in MULTIPLE files

Verified: `ui/index.html` contains 290 double-encoded sequences AND `ui/core.js` is also affected (e.g. `âœ…` where ✅ belongs, `â€"` in offline messages). The corruption is baked into file bytes (UTF-8 read as CP-1252, re-saved as UTF-8) — the `<meta charset>` is fine, `cockpit.js` is clean. Fix: run an encoding repair across ALL `ui/` files (reverse the double-encoding: bytes → decode UTF-8 → encode CP-1252 → decode UTF-8, applied only to files that contain the marker sequences), then verify `grep -rc "â€" ui/` returns zero. Add that grep to the pre-commit verification list so it can't return silently.

## 6. Already fixed — do not re-open

- SIP tilt no longer shows the degenerate all-7.14% table; it now shows the honest "not yet available — template not validated" state (correct per plan §7.0.3).
- Cockpit no longer renders stale ML confidence badges alongside NO DATA prices (correct per plan §7.0.2).

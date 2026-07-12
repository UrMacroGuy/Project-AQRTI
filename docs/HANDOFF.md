# HANDOFF.md — Self-serve walkthrough (written 2026-07-12)

Everything still open, decided, or worth doing — written so you (or any future session) can act without prior conversation context. Read top to bottom once; then it's a reference.

## 0. Do first: rotate the three leaked API keys (~10 minutes)

The GitHub repo is **public** and an old commit (f0ab958) put `backend/.env` with real keys into history. The file is untracked now, but git history is forever — treat all three keys as compromised:

1. **NVIDIA NIM** — build.nvidia.com → your profile → API keys → revoke old, generate new → paste into `backend/.env` as `NVIDIA_NIM_API_KEY=`.
2. **OpenRouter** — openrouter.ai/settings/keys → delete old, create new → `OPENROUTER_API_KEY=`.
3. **Finnhub** — finnhub.io/dashboard → regenerate → `AQRTI_FINNHUB_API_KEY=`.

Verify: restart the backend and check the boot log shows research synthesis running via `nvidia_nim` with no "not configured" warning.

## 1. Operating routine

**Daily (2 minutes):** the backend runs itself via Windows Scheduled Tasks (`AQRTI Backend` / `AQRTI Watchdog` / `AQRTI Scheduler`; daily pipeline at 15:30 IST). Open the Cockpit, glance at prices/synthesis, read the Go/No-Go morning verdict. Expect "NO-GO — no promoted algos yet" for a while; that's honest.

**Monthly (30 minutes):**
- Execute the SIP: ₹500 Nifty 50 index fund + ₹700 toward whichever of BEL/HDFCBANK/NTPC the monthly allocation suggests (`GET /api/v1/monthly-allocation`, also on the Cockpit) + ₹800 fractional VOO/QQQ (70/30) on INDmoney.
- **Record every real transaction in the portfolio tracker the same day.** This is what activates paper-vs-real reconciliation and builds your tax audit trail.
- Re-run walk-forward: `cd backend && .venv\Scripts\activate && python scripts/walk_forward_templates.py`. A template passes at WFO Sharpe ≥ 0.7. If one passes: do nothing — quarantine starts automatically and runs ≥60 days.

**Quarterly:** if any algo is promoted and live, re-run walk-forward on it and check the live-validator triggers haven't quietly demoted it.

## 2. Still open (with walkthroughs)

**a. Research synthesis coverage (the main bottleneck — currently a wait, not a bug).** Only HDFCBANK/ICICIBANK/INFY have synthesis rows; BEL/NTPC/CDSL/DRREDDY/LT/HAL have zero because those names simply haven't appeared in collected news yet (entity aliases are verified correct; stale rows were purged 2026-07-12). Weekly check:
```
cd backend && .venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('aqrti.db').execute('SELECT symbol,COUNT(*) FROM research_synthesis GROUP BY symbol').fetchall())"
```
If PSU/defence names are still at zero after 3-4 weeks, add sector-specific sources to `backend/news/news_collector.py::RSS_SOURCES` (each entry is `{name, url, weight}` — candidates: Business Standard defence RSS, Moneycontrol sector feeds). New sources flow through the existing parser/classifier automatically.

**b. VOO/QQQ live prices.** The symbol map now builds them without the `.NS` suffix and yfinance supports US tickers — but this was wired without a live-market verification. With the backend running during US hours, hit `GET /api/v1/market/live/stocks` and confirm VOO/QQQ return prices. If they do, remove the "PRICE FEED PENDING" label from their Cockpit cards.

**c. The templates' zero-trade status.** 0/7 pass WFO, mostly because research/regime feature history doesn't exist far enough back to trigger entries in backtests. This fixes itself only through calendar time as the daily pipeline accumulates `ResearchSynthesis` history. Do not backfill synthetic history to force trades — that's the cardinal sin here.

## 3. Decisions only you can make

1. **Momentum vs the 50% win-rate floor.** The strategy lab's strongest raw edge was 52-week-high momentum: +3.6%/trade average but 43.8% win rate — structurally banned by your floor. Options: keep the floor as-is (momentum stays out), or add a second gate profile for low-WR/high-payoff families (e.g. expectancy ≥ +1%/trade net AND max drawdown cap AND profit factor ≥ 1.5, instead of WR). If you choose the second, tell the next session: "implement the expectancy-based gate profile from HANDOFF.md §3.1" — the numbers to validate against are in docs/STRATEGY_LAB.md.
2. **Telegram alerts** (optional, ~10 min): create a bot via @BotFather, get your chat ID via @userinfobot, set `AQRTI_TELEGRAM_BOT_TOKEN` and `AQRTI_TELEGRAM_CHAT_ID` in `.env`. Promotion/demotion alerts then fire automatically (the send path was fixed 2026-07-07).
3. **Markov module graduation.** `backend/markov/` still carries its "isolated/experimental" framing while `regime_pullback_v2` conceptually leans on NIFTY regime. If its regime calls keep matching reality, a future session can wire `markov_hmm_regime_daily` directly into template conditions — that's an architecture change; ask for it explicitly.

## 4. Worth adding (each is a small, safe task for a future session)

- **Weekly DB backup task:** a scheduled task copying `backend/aqrti.db` → `aqrti.db.bak-YYYYMMDD` (keep last 4). Currently backups only happen ad-hoc before bulk mutations.
- **Mojibake pre-commit guard:** `grep -rc "â€" ui/` must return zero — the double-encoding corruption has slipped in twice; a pre-commit hook ends that.
- **US ETF synthesis labels:** VOO/QQQ cards should say "US ETF — synthesis not applicable" (they'll never have NSE filings).

## 5. Worth removing (safe deletions when convenient)

- Unused AQRTINet source files: `backend/ml/models/aqrtinet_model.py`, `aqrtinet_percentile.py` — nothing in production imports them (verified 2026-07-07).
- Any stragglers a grep finds: `grep -rn "RELIANCE\|AXISBANK\|BAJFINANCE" backend/ --include=*.py` — old-universe symbols in live code paths (comments/tests are fine).

## 6. Troubleshooting quick reference

| Symptom | Cause & fix |
|---|---|
| `database is locked` | Backend + manual script writing simultaneously. Stop the backend for heavy writes. A slow feature regen is NOT necessarily a hang. |
| Prices show last close, not live | yfinance down or market closed — the DB fallback is working as designed. |
| "Active LLM provider … is not configured" in boot log | `.env` not loading or key invalid. `load_dotenv()` must exist at the top of both `backend/main.py` and `backend/aqrti/api/app.py` (bug fixed 2026-07-11c — check it didn't regress), then verify the key. |
| gstack "Server failed to start within 15s" | Zombie process: kill all `browse`/`bun` processes, then retry. Git Bash may need `export PATH="$HOME/.bun/bin:$PATH"`. Rebuild fails with EPERM while browse.exe runs. |
| Two python processes fighting over port 8000 | Stale `backend/start_backend.lock` — run `STOP AQRTI.bat`, then start once. |
| Garbled characters (`â€"`) in UI | Encoding regression — see §4 guard; repair = decode CP-1252→UTF-8 reversal on affected files only. |

## 7. For future Claude sessions

Bootstrap order: `plans/CHANGELOG.md` top entries → this file → `docs/RESEARCH_DRIVEN_REARCHITECTURE.md`. The standing rules live in `CLAUDE.md` (quant-strategist doctrine + hard rules). The one-sentence summary of this project's soul: **an honest zero beats a fabricated signal, every time.**

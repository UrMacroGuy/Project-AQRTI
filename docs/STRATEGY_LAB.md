# STRATEGY_LAB.md — Designing an original algo on AQRTI's real data (2026-07-11)

This is the honest record of a full strategy R&D cycle run against the project's own price database: literature research → hypothesis → in-sample tuning → out-of-sample test → verdict. **The verdict is negative — the candidate does not currently clear the quant bar — and per CLAUDE.md's hard rules, that finding ships as-is rather than being tweaked until it looks good.** Read to the end: the negative result is genuinely informative and shapes what the engine should do next.

## 1. What the research says (web research, July 2026)

Documented effects in **Indian** equities specifically: 6-12 month momentum replicates on NSE (Jegadeesh-Titman-style, multiple studies incl. Sehgal & Balakrishnan; ~8%/yr alpha on Nifty 500, 2005-2022 per an IIMA study), the 52-week-high effect is separately robust (SSRN, 2004-2023 NSE data), and turn-of-month days [-1,+2] carry ~4× the average daily return. Caution flags: short-term *reversal* in India concentrates in illiquid stocks — liquid large-caps (our universe) lean toward short-term momentum instead; expiry-week patterns are regime-broken by NSE's 2025 expiry-day changes.

Realistic edges after ~0.3% costs: Connors-style RSI-2 pullback systems publish 65-79% win rates with small (~0.5-1% gross) average wins — thin after costs; momentum systems publish 35-45% win rates with 2-3× win/loss ratios (fails our ≥50% WR floor by construction). Published combined rule with post-publication persistence (US data): long when close > 200DMA, buy RSI(2) < 5-10, exit close > 5DMA — 62-76% WR on equities, 1-5 day holds. No formal NSE replication exists — validating the transfer was exactly this exercise.

Known pitfalls the harness controlled for: signal-at-close vs next-open execution (we model **next-open fills**, the conservative choice, costing 0.2-0.5% of paper edge), hard stops making mean-reversion worse (confirmed below), gaps through stops (stops fill at `min(stop, open)`), and survivorship bias — **our 9-symbol curated universe is itself survivorship-biased** (we picked 2026's winners), so even these results overstate live edge.

## 2. Methodology (the part that makes this trustworthy)

- Data: real `daily_prices` from `aqrti.db`, 10,253 rows, 9 symbols, 2021-06-29 → 2026-07-10. No synthetic data anywhere.
- Costs: 0.28% NSE round-trip (0.154% buy / 0.126% sell), matching the production backtester.
- Execution: signal on day *d* close → fill at day *d+1* open. No look-ahead by construction.
- Discipline: parameters tuned ONLY on train (≤2024-12-31). The 2025-01→2026-07 window was held out and spent **once** on the pre-registered finalist.

## 3. Candidate screening (train window only, ≤2024-12-31)

| Variant | Rule sketch | n | WR | avg/trade (net) |
|---|---|---|---|---|
| A | close>200DMA, RSI(2)<10 → exit close>5DMA | 163 | 61.3% | +0.34% |
| A+stop | same + 3×ATR hard stop | 169 | 59.8% | +0.04% |
| B | close>200DMA, RSI(3)<15 → exit RSI(3)>70, 12d time stop | 106 | 74.5% | +1.41% |
| C | close>200DMA, 7-day-low → exit close>5DMA | 253 | 62.8% | +0.34% |
| D | 52wk-high momentum (≥0.95×hi, 6m ret>10%) | 80 | 43.8% | +3.62% |

Notes: the hard stop *degraded* the mean-reversion system (exactly as Connors published — confirmed independently on NSE data). D (momentum) has the biggest expectancy but a 43.8% WR — structurally below the user's 50% floor. B was pre-registered as the finalist: robust across a 3×3 parameter grid (65-77% WR, +1.06→+1.57% avg on all combos — the edge didn't collapse under parameter wiggle), consistent per-year (2022: 84% WR, 2023: 69%, 2024: 75%) and positive on all 9 symbols.

## 4. The out-of-sample test — FAILED

Finalist B on the untouched 2025-01→2026-07 window:

| Window | n | WR | avg/trade | avg win | avg loss | worst | profit factor |
|---|---|---|---|---|---|---|---|
| Train 2022-24 | 106 | 74.5% | +1.41% | +2.81% | -2.67% | — | ~2.4 |
| **OOS 2025-26** | **47** | **61.7%** | **-0.71%** | +2.57% | **-6.01%** | **-20.0%** | **0.69** |

The win rate held (61.7% — above the 50% floor!) but the **loss tail exploded**: the slow RSI-exit + 12-day time-hold sat through falling knives once the market regime turned (2025-26 IT de-rating: INFY trades averaged -8.6%; one -20% trade). NIFTY buy-and-hold over the same window: +2.0%. **A win-rate floor alone is not protection — expectancy died while WR stayed "good." This is why the promotion gates check both.**

## 5. One principled revision (v2) — honestly labeled as post-OOS iteration

Because the failure mode (bear-regime holds) is a *published* weakness of this system family with a *published* remedy — the faster close>5DMA exit and an index-level regime filter — one revision was tested: entry additionally requires NIFTY > its own 200DMA; exit on close>5DMA; 7-day time stop. Evaluated per-year across the full 5 years (each year an unseen slice under fixed rules):

| Year | n | WR | avg/trade |
|---|---|---|---|
| 2022 | 16 | 56.3% | -0.04% |
| 2023 | 30 | 43.3% | -0.36% |
| 2024 | 57 | 73.7% | +1.33% |
| 2025 | 29 | 62.1% | +0.32% |
| 2026 (H1) | 4 | 25.0% | -3.11% |

Full-period: 136 trades, 61.0% WR, +0.45% avg, PF 1.60, worst -10.7%. Looks decent — until you see that **the entire edge is 2024**. The 2025-26 slice nets -0.09%/trade (PF 0.89). And because v2 was designed *after* seeing v1's OOS failure, its numbers carry contamination and deserve extra skepticism, not less.

## 6. Verdict

**Not tradeable today.** The classic trend+pullback edge on this universe is a bull-regime phenomenon that hasn't paid for its costs in the last 18 months. Publishing this as a "good strategy" would violate everything the promotion pipeline stands for. What this cycle DID produce:

1. **A validated negative**: mean-reversion pullback systems on these 9 liquid large-caps currently net ≈0 after 0.28% costs. The engine should not waste evolution cycles re-discovering this.
2. **A confirmed methodology**: the harness (next-open fills, honest costs, train/OOS discipline, parameter-robustness grids) caught a strategy that a naive backtest would have shipped with "74.5% WR, +1.41%/trade" — which is precisely the kind of inflated claim the 2026-07-02 trust overhaul purged.
3. **Two transferable findings**: hard stops hurt this system family on NSE too (matches published US results); and WR alone is a dangerous gate — the 50% floor must always ride with the expectancy/benchmark/drawdown gates, never alone.

## 7. What's next (the plan)

1. **Fix the FIX.md items** — stale `_NSE_STOCKS_MAP` (cockpit NO DATA), topbar index fallback, Go/No-Go loading states — so the dashboard reflects reality daily.
2. **Let research history accumulate.** The 6 templates' WFO failures (0/6 passing) are partly data-starvation: `research_synthesis` has days of history, not years. Every day the scheduler runs, `ResearchSentiment`/`CatalystPresent` conditions gain real history to validate against. Re-run `walk_forward_templates.py` monthly.
3. **Add `regime_pullback_v2` (this doc's §5) as a 7th template** in the generator — NOT as a trusted algo, but as a candidate the honest gates will keep rejecting until market conditions or refinements change the verdict. Its per-year record becomes a living regime indicator at zero extra cost.
4. **The momentum finding deserves a different harness**: variant D's +3.6%/trade at 43.8% WR is the strongest raw edge found, and Indian literature backs momentum — but it needs the ≥50%-WR floor rethought for low-WR/high-payoff families (e.g., floor on expectancy + max-drawdown instead). That's a user decision — the floor is the user's bottom line, so flagging, not changing.
5. **Keep the SIP running regardless.** The ₹500 index core + ₹700 satellites + ₹800 US plan does not depend on any algo passing gates — that's the point of its design. Algos add tactical edge only when they've earned trust; the compounding never waits for them.

*Everything in this document is reproducible: harness at the session scratchpad `bt.py`/`exp.py` (pin into `backend/scripts/strategy_lab/` if this line of work continues). All numbers are net of 0.28% costs with next-open execution on real DB prices.*

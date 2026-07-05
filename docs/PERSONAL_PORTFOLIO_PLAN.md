# Personal Portfolio Module — Design Plan

*Planning document (no code yet). Defines the new AQRTI section that tracks the user's real 60-40 investment plan with real-time data, and how the algo engine trains on these instruments' 5-year history. Work items live in `IMPROVEMENTS.md` §P-PF; this doc is the spec they implement against.*

Created 2026-07-05. Status: **PLANNED — not yet built.**

---

## 1. What this module is

A new dashboard section ("**My Portfolio**") that tracks the user's actual real-money investment plan — executed manually on Zerodha and INDmoney — inside AQRTI, with live prices, allocation drift, projections vs. actuals, and tax/action reminders.

**Hard boundaries (consistent with CLAUDE.md rules):**
- **AQRTI never executes anything.** This module is a tracker + advisor. The user buys/sells manually on Zerodha/INDmoney and records the transaction in AQRTI (manual entry or CSV import). No broker API write access, ever.
- **Fully separate from paper trading and the algo population.** Own tables, own page, own P&L. Real money is never mixed with the ₹1,00,000 virtual book, and portfolio holdings never seed algo positions.
- **No placeholder data.** Until the user records their first real transaction, the page shows the plan (targets) and an explicit "no holdings recorded yet" state — never simulated holdings.

## 2. The plan being tracked (user's actual allocation, ₹2,000/month)

### India — 60% (₹1,200/month)
| # | Instrument | Type | Cadence | Amount | Platform | Risk |
|---|---|---|---|---|---|---|
| 1 | Nifty 50 Index Fund | Mutual fund (SIP) | Monthly | ₹600 | Zerodha Coin | Low |
| 2 | TCS | Stock (Q1: Jan-Mar) | Quarterly | ₹300 | Zerodha Kite | Medium |
| 3 | Infosys | Stock (Q2: Apr-Jun) | Quarterly | ₹300 | Zerodha Kite | Medium |
| 4 | HDFC Bank | Stock (Q3: Jul-Sep) | Quarterly | ₹300 | Zerodha Kite | Med-High |
| 5 | Reliance | Stock (Q4: Oct-Dec) | Quarterly | ₹300 | Zerodha Kite | Medium |
| 6 | Nifty Smallcap 250 Index Fund | Mutual fund (SIP) | Monthly | ₹200 | Zerodha Coin | High |
| 7 | Gold ETF | ETF | Monthly | ₹100 | Zerodha Kite | Low |

### US — 40% (₹800/month)
| # | Instrument | Type | Cadence | Amount | Platform | Risk |
|---|---|---|---|---|---|---|
| 8 | VTI (Vanguard Total Stock Market) | ETF | Monthly | ₹400 | INDmoney | Low |
| 9 | PLTR (Palantir) | Stock | Monthly | ₹250 | INDmoney | Med-High |
| 10 | LMT (Lockheed Martin) | Stock | Monthly | ₹150 | INDmoney | Medium |

**Risk buckets:** Low/safe-core 45% (Nifty50 fund + Gold + VTI = ₹1,100) · Medium/growth 40% (quarterly stock + LMT) · High/moonshot 15% (Smallcap fund + PLTR = ₹450, noting PLTR ₹250 + smallcap ₹200).

**User's stated projections** (stored as *plan assumptions*, displayed as such — AQRTI tracks actuals against them, it does not endorse them): blended CAGR 12.5%; 5yr: ₹120k invested → ₹203.4k; 10yr: ₹240k invested → ₹806k; ~20% LTCG on exit.

## 3. Data sources — verified vs. to-verify

| Instrument | Live/EOD price source | Status |
|---|---|---|
| TCS, INFY, HDFCBANK, RELIANCE | Already in AQRTI universe with 5yr `DailyPrice` history | ✅ nothing to add |
| PLTR, LMT | Already in `global_universe.py` (US region) | ✅ verify 5yr price + feature coverage |
| VTI | **Not in universe** — yfinance carries it | ➕ add ticker + 5yr backfill |
| Gold ETF | **Ticker unverified** — user wrote "GOLDNXT"; NSE gold ETFs resolvable via yfinance include GOLDBEES.NS and others. **Must verify the exact instrument the user actually buys before adding — do not guess.** | ⚠️ verify with user/first transaction |
| Nifty 50 Index Fund (Coin) | Mutual funds have **no intraday price** — daily NAV via **AMFI's free public NAV feed** (`amfiindia.com` NAVAll text file). Need the exact scheme code once the user picks the fund (e.g. UTI/HDFC/ICICI Nifty 50 Index Growth-Direct). | ➕ new NAV ingester + scheme code from user |
| Nifty Smallcap 250 Index Fund | Same — AMFI NAV by scheme code | ➕ same |
| USD/INR | yfinance `INR=X` (already used in macro layer) | ✅ needed to value US holdings in ₹ |

**Honesty rule for this page:** every price shows its timestamp and source ("NAV as of 2026-07-04, AMFI" / "delayed quote, yfinance"). Mutual-fund values are always previous-day NAV — the UI must say so rather than pretend real-time.

## 4. Data model (new tables — parallel to, never mixed with, paper trading)

Follows the index-futures precedent: separate tables, clean discriminators, defined in `backend/aqrti/database/models.py`.

- **`PortfolioInstrument`** — the 10 planned instruments: symbol/scheme_code, name, instrument_type (`stock|etf|mutual_fund`), market (`IN|US`), currency, platform (`zerodha_kite|zerodha_coin|indmoney`), risk_bucket (`low|medium|high`), plan_amount, plan_cadence (`monthly|quarterly`), plan_quarter (1-4 for the rotation stocks), plan_cagr_assumption, active flag.
- **`PortfolioTransaction`** — every real buy/sell the user records: instrument_id, txn_date, side, units (fractional — MF/US support fractions), price_per_unit, price_currency, fx_rate_at_txn (USD/INR for US buys), gross_amount_inr, fees, platform_ref/note, created_at. **Immutable once entered** (corrections = reversal + new row, keeping an audit trail for tax).
- **`PortfolioHolding`** — derived current position per instrument (units, avg cost ₹, invested ₹) — recomputed from transactions, never hand-edited.
- **`PortfolioValuation`** — daily snapshot per instrument + total: units × latest price/NAV × fx, invested-to-date, unrealized P&L, XIRR-to-date, allocation %. Powers the equity curve.
- **`MutualFundNAV`** — scheme_code, date, nav (AMFI ingester writes here; MF instruments valued from this, not `DailyPrice`).
- **`PortfolioActionLog`** — generated reminders and their completion: quarterly-rotation buys (Jan/Apr/Jul/Oct 1), monthly SIP confirmations, ITR Schedule FA (by Jul 31 yearly), 24-month LTCG eligibility dates per tax lot.

## 5. The "My Portfolio" page (UI section #15)

1. **Header strip** — total value ₹, invested ₹, unrealized P&L, XIRR, last-updated timestamps per source.
2. **Allocation vs. target** — actual India/US split vs 60/40 and per-risk-bucket vs 45/40/15, with drift bars; flag when drift > 5pp.
3. **Holdings table** — per instrument: units, avg cost, LTP/NAV (+source+timestamp), value ₹, P&L, weight, plan vs actual invested.
4. **Plan tracker** — this month's checklist auto-generated from the plan (₹600 Nifty50 SIP, ₹200 smallcap, ₹100 gold, ₹400 VTI, ₹250 PLTR, ₹150 LMT + the current quarter's ₹300 rotation stock) with done/pending state from recorded transactions.
5. **Projections vs. actuals** — the user's 5yr/10yr projection curves (labeled "plan assumption, 12.5% blended CAGR") with the real portfolio line overlaid.
6. **Tax panel** — Schedule FA reminder (US holdings, ITR by Jul 31), per-lot LTCG countdown (24 months), estimated tax on hypothetical exit at current prices.
7. **AQRTI intelligence overlay (read-only)** — what AQRTI's ML predictions/sentiment/regime currently say about TCS/INFY/HDFCBANK/RELIANCE/PLTR/LMT. Clearly advisory: "AQRTI's view — not a directive." No overlay for index funds (no single-stock signal applies).

**Backend:** new route module `aqrti/api/routes/portfolio.py` under `/api/v1/portfolio/*` (instruments, transactions CRUD-append, holdings, valuation, actions). Daily scheduler step: refresh NAVs + fx + valuations after market close; US valuation refresh after US close (~2:00 IST) or at next boot.

## 6. Algo training on these instruments (5yr)

Goal: the algo engine trains/evaluates on the portfolio's tradeable instruments' 5-year history too.

- **Already covered:** TCS, INFY, HDFCBANK, RELIANCE are in the NSE universe — algos already backtest on them (they pass the ₹5cr turnover liquidity filter easily). PLTR/LMT have universe entries; verify 5yr `DailyPrice` + `FeatureValue` coverage and backfill gaps.
- **To add:** VTI and the verified gold ETF → `global_universe.py`, 5yr backfill, feature generation.
- **Mutual funds are excluded from algo training** — daily NAV has no OHLC/volume microstructure; training entry/exit algos on NAV series would be pseudo-realism. They remain tracked-only instruments.
- **Segment isolation (follow the `asset_class` precedent):** the main NSE algo population stays NSE-only (its cost model, liquidity filter, and NIFTY benchmark gate are India-specific). For US instruments (PLTR, LMT, VTI), create a separate **`us_portfolio` asset-class segment** — own generation/backtest track with US cost model (~0.10%), no NSE circuit-band logic, benchmark gate vs. buy-and-hold **VTI** (not NIFTY), never competing with or breeding into the stock/index-futures populations.
- **Portfolio-focus evaluation:** add a per-algo evaluation view (not a gate) showing performance restricted to the user's held names, so the intelligence overlay in §5.7 can say "AQRTI's best algo for TCS specifically."

## 7. Explicitly out of scope

- Broker API integration (Zerodha/INDmoney) for automatic transaction sync — manual entry/CSV first; revisit only if manual entry proves painful.
- Any auto-execution or order placement. Never.
- Options/derivatives on portfolio names.
- Live streaming prices — EOD + on-demand refresh is sufficient for a monthly-SIP portfolio.

## 8. Build order (mirrors IMPROVEMENTS.md §P-PF)

1. Verify instruments (gold ETF ticker, MF scheme codes, PLTR/LMT data coverage) — **blocks everything else.**
2. Schema + migration (tables in §4).
3. Data ingestion: VTI/gold backfill, AMFI NAV ingester, USD/INR valuation path.
4. API routes + valuation engine (XIRR, drift, tax lots).
5. UI page #15 with plan tracker + honest empty states.
6. Scheduler wiring + action reminders.
7. US algo segment (§6) — last; independent of the tracker pages.

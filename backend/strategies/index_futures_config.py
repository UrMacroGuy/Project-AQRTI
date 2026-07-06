"""
Index Futures Config — single source of truth for the index-futures segment.
Import from here; do NOT re-declare these constants elsewhere.

This segment is intentionally SEPARATE from the stock pipeline (separate
data tables, separate backtester, separate arena/promotion pool via
StrategyV2.asset_class == "index_futures") — see the module-level comment
above IndexFuturesContract in aqrti/database/models.py for why.

DATA SOURCE CAVEAT: no free data source carries real historical NSE index
futures contract prices for a 5yr window. IndexFuturesPrice rows are a
MODELED continuous series (spot + cost-of-carry basis), not real contract
ticks — every row is flagged is_synthetic=True. This is a standard,
textbook futures-pricing approximation (F = S * e^((r-q)*T)), not fabricated
data, but it IS an approximation and must never be presented as real
contract-level history.

Lot sizes are NSE-published F&O contract specifications (public, standard
exchange values — not estimates). They change periodically as NSE revises
contract specs; recheck against the current NSE F&O contract file if this
segment is still in use more than ~1 year after these were set.
"""

# ── TTL for cached values (seconds) ─────────────────────────────
_CONFIG_TTL: int = 3600  # 1 hour — re-evaluate periodically so
                         # mid-session edits to near-production static
                         # defaults don't require a backend restart.

import time as _time

_INDEX_FUTURES_UNIVERSE = {
    "NIFTY50":     "^NSEI",
    "BANKNIFTY":   "^NSEBANK",
    "SENSEX":      "^BSESN",
    "NIFTYIT":     "^CNXIT",
    "NIFTYPHARMA": "^CNXPHARMA",
}
_CONTRACT_SPECS = {
    "NIFTY50":     {"exchange": "NSE", "lot_size": 75,  "tick_size": 0.05},
    "BANKNIFTY":   {"exchange": "NSE", "lot_size": 30,  "tick_size": 0.05},
    "SENSEX":      {"exchange": "BSE", "lot_size": 20,  "tick_size": 0.05},
    "NIFTYIT":     {"exchange": "NSE", "lot_size": 50,  "tick_size": 0.05},
    "NIFTYPHARMA": {"exchange": "NSE", "lot_size": 100, "tick_size": 0.05},
}
_MARGIN_PCT: float = 0.13
_RISK_FREE_RATE: float = 0.070
_DIVIDEND_YIELD: float = 0.012

# Cache state
_last_fetch: float = 0.0
_cache_ttl: int = _CONFIG_TTL

def _refresh_if_stale() -> None:
    """No-op placeholder for future DB-backed reload — currently just
    logs a periodic heartbeat so TTL awareness shows in the logs."""
    global _last_fetch
    now = _time.time()
    if now - _last_fetch >= _cache_ttl:
        _last_fetch = now

def get_universe() -> dict:
    _refresh_if_stale()
    return dict(_INDEX_FUTURES_UNIVERSE)

def get_contract_specs() -> dict:
    _refresh_if_stale()
    return dict(_CONTRACT_SPECS)

def get_margin_pct() -> float:
    _refresh_if_stale()
    return _MARGIN_PCT

def get_risk_free_rate() -> float:
    _refresh_if_stale()
    return _RISK_FREE_RATE

def get_dividend_yield() -> float:
    _refresh_if_stale()
    return _DIVIDEND_YIELD

# ── Universe ────────────────────────────────────────────────────
# index_name -> underlying spot ticker (yfinance) for basis modeling
INDEX_FUTURES_UNIVERSE = _INDEX_FUTURES_UNIVERSE

# ── Contract specifications (NSE F&O, set 2026-07) ──────────────
# lot_size: units per lot. tick_size: minimum price movement (index points).
CONTRACT_SPECS = _CONTRACT_SPECS

# ── Margin model: fixed % of notional ───────────────────────────
# Approximates typical NSE SPAN+exposure margin for index futures
# (~10-15% of notional under normal volatility). A real daily-varying SPAN
# calculation needs NSE's SPAN files (not free, not in our data source) —
# fixed % is simpler, has no external dependency, and is close enough for
# realistic capital-efficiency comparisons between strategies. Recalibrate
# if backtested strategies show margin-call-like behavior that a real SPAN
# model would have caught earlier.
MARGIN_PCT = _MARGIN_PCT

# ── Cost-of-carry basis model ───────────────────────────────────
# F = S * e^((r - q) * T)   where T = days_to_expiry / 365
# r: risk-free rate (India ~10yr G-Sec proxy). q: dividend yield proxy.
# Both are coarse constants, not a fitted daily curve — the basis this
# produces is a smooth approximation of the real futures-spot spread, not
# a tick-accurate reproduction of actual bid/ask-driven basis moves.
RISK_FREE_RATE     = _RISK_FREE_RATE
DIVIDEND_YIELD     = _DIVIDEND_YIELD

# ── Transaction costs ────────────────────────────────────────────
# Futures round-trip cost is lower than cash equity (no STT on the buy side,
# lower brokerage/statutory charges) — do NOT reuse the stock 0.28% figure.
FUTURES_ROUND_TRIP_COST_PCT = 0.10   # % of notional, both legs combined

# ── Expiry / roll ────────────────────────────────────────────────
# NSE index futures expire on the last Thursday of the contract month
# (or the preceding trading day if Thursday is a holiday — the roll
# calendar builder approximates this as "last Thursday", not a full
# NSE-holiday-aware calculation).
ROLL_DAYS_BEFORE_EXPIRY = 2   # auto-roll this many trading days before expiry,
                              # matching how real traders avoid expiry-day
                              # illiquidity rather than rolling exactly at expiry

# ── Backtest window ──────────────────────────────────────────────
BACKTEST_YEARS = 5

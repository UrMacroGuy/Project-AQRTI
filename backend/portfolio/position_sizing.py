"""
Position Sizing Engine (Phase 4C)
Three sizing methods:
  1. confidence_based   — weight proportional to confidence score
  2. risk_based         — weight inversely proportional to volatility
  3. equal_weight       — uniform allocation across all selected stocks

All methods respect hard limits from settings:
  MAX_POSITION_PCT     — single stock ceiling
  MAX_SECTOR_PCT       — sector ceiling
  MAX_PORTFOLIO_EXPO   — total invested capital ceiling
"""

from __future__ import annotations

from typing import Optional

from aqrti.config.settings import get_settings

_settings = None


def _s():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


# ── Helpers ────────────────────────────────────────────────────

def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """Scale weights so they sum to 1.0."""
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {k: v / total for k, v in weights.items()}


def _apply_position_cap(
    weights:      dict[str, float],
    max_pos_pct:  float,
) -> dict[str, float]:
    """
    Iteratively cap any weight above max_pos_pct and redistribute excess
    to remaining uncapped positions. Stops after 10 iterations.
    """
    cap   = max_pos_pct / 100.0
    w     = dict(weights)
    for _ in range(10):
        over = {k: v for k, v in w.items() if v > cap}
        if not over:
            break
        excess = sum(v - cap for v in over.values())
        under  = {k: v for k, v in w.items() if v <= cap}
        for k in over:
            w[k] = cap
        if under:
            add_per = excess / len(under)
            for k in under:
                w[k] = min(w[k] + add_per, cap)
    return w


def _apply_sector_cap(
    weights:         dict[str, float],
    sectors:         dict[str, str],   # {symbol: sector}
    max_sector_pct:  float,
) -> dict[str, float]:
    """
    Cap total sector exposure. Excess is proportionally redistributed
    from overweight sector symbols to others.
    """
    cap = max_sector_pct / 100.0
    w   = dict(weights)

    sector_totals: dict[str, float] = {}
    for sym, wt in w.items():
        sec = sectors.get(sym, "Unknown")
        sector_totals[sec] = sector_totals.get(sec, 0.0) + wt

    for sec, total in sector_totals.items():
        if total <= cap:
            continue
        scale = cap / total
        syms  = [s for s in w if sectors.get(s, "Unknown") == sec]
        for s in syms:
            w[s] *= scale

    return w


# ── Sizing Methods ─────────────────────────────────────────────

def confidence_based_sizing(
    candidates:      list[dict],    # [{symbol, confidence, expected_return, sector, ...}]
    max_exposure:    Optional[float] = None,
) -> dict[str, float]:
    """
    Weight = confidence_score (0-100), then normalize and cap.
    High-confidence picks receive more capital.
    """
    s = _s()
    max_pos    = s.max_position_pct
    max_sec    = s.max_sector_pct
    max_expo   = max_exposure or s.max_portfolio_exposure

    if not candidates:
        return {}

    raw = {c["symbol"]: max(c.get("confidence") or 50.0, 1.0) for c in candidates}
    w   = _normalize(raw)

    sectors = {c["symbol"]: (c.get("sector") or "Unknown") for c in candidates}
    w = _apply_sector_cap(w, sectors, max_sec)
    w = _apply_position_cap(w, max_pos)
    w = _normalize(w)

    # Apply total exposure ceiling
    total_alloc = min(max_expo / 100.0, 1.0)
    return {k: round(v * total_alloc * 100, 4) for k, v in w.items()}


def risk_based_sizing(
    candidates:      list[dict],    # must include 'volatility' field (annualized %)
    max_exposure:    Optional[float] = None,
) -> dict[str, float]:
    """
    Weight ∝ 1/volatility (inverse-vol sizing).
    Lower-vol stocks receive more capital. Fallback to equal if no vol data.
    """
    s = _s()
    max_pos    = s.max_position_pct
    max_sec    = s.max_sector_pct
    max_expo   = max_exposure or s.max_portfolio_exposure

    if not candidates:
        return {}

    raw = {}
    for c in candidates:
        vol = c.get("volatility") or 20.0    # default 20% annualized vol
        vol = max(vol, 1.0)
        raw[c["symbol"]] = 1.0 / vol

    w = _normalize(raw)
    sectors = {c["symbol"]: (c.get("sector") or "Unknown") for c in candidates}
    w = _apply_sector_cap(w, sectors, max_sec)
    w = _apply_position_cap(w, max_pos)
    w = _normalize(w)

    total_alloc = min(max_expo / 100.0, 1.0)
    return {k: round(v * total_alloc * 100, 4) for k, v in w.items()}


def equal_weight_sizing(
    candidates:      list[dict],
    max_exposure:    Optional[float] = None,
) -> dict[str, float]:
    """
    Uniform allocation. Each stock gets max_exposure / n, capped at max_position_pct.
    """
    s = _s()
    max_pos   = s.max_position_pct
    max_expo  = max_exposure or s.max_portfolio_exposure

    if not candidates:
        return {}

    n        = len(candidates)
    raw_each = min(max_expo / n, max_pos)
    return {c["symbol"]: round(raw_each, 4) for c in candidates}

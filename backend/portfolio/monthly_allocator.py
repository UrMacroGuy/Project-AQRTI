"""
Monthly Capital Allocator
Suggests where the month's satellite budget (₹700/month across BEL,
HDFCBANK, NTPC per docs/RESEARCH_DRIVEN_REARCHITECTURE.md) should tilt,
ranking the 3 owned satellites by conviction: live win-rate history (if a
strategy is promoted/active and trading it), regime fit, and research
synthesis strength.

This is a SUGGESTION ONLY — never a trade instruction. The user allocates
their real ₹700/month manually; this ranks the 3 names by how strong the
current case for each is, per CLAUDE.md's Personal Portfolio rules
("suggestions, not advice — you decide").

Falls back gracefully at every stage: no promoted strategies -> conviction
is research-synthesis-only; no research synthesis for a symbol -> that
symbol scores 0 conviction (never fabricated), not excluded from the
ranking (an equal split is still a valid suggestion when nothing
differentiates the three).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, PaperTrade, ResearchSynthesis, MarketRegime
from aqrti.utils.logger import get_logger

log = get_logger("monthly_allocator")

# The owned Tier 1 satellites the ₹700/month accumulates into (see
# strategy_generator.py::TIER1_OWNED_SYMBOLS — single source of truth for
# the split of the curated universe into owned vs bench; kept in sync
# manually per the architecture doc's documented drift risk).
SATELLITE_SYMBOLS = ["BEL", "HDFCBANK", "NTPC"]

SATELLITE_MONTHLY_BUDGET_INR = 700.0

# Conviction score weights — sum to 1.0. live win-rate history matters most
# (it's the only component backed by actual trading outcomes, not just a
# thesis); regime fit and research strength are secondary tilts.
WEIGHT_LIVE_WIN_RATE = 0.5
WEIGHT_REGIME_FIT = 0.2
WEIGHT_RESEARCH_STRENGTH = 0.3

ROLLING_TRADE_WINDOW = 20  # matches live_validator.ROLLING_WR_WINDOW


def _live_win_rate_score(db: Session, symbol: str) -> Optional[float]:
    """
    0..1 score from the rolling win rate of closed paper trades on this
    symbol across ANY promoted/active strategy. Returns None (not 0) if
    there's no live trade history yet — the caller must not silently treat
    "no data" the same as "proven bad."
    """
    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.symbol == symbol, PaperTrade.is_open == False)
        .order_by(PaperTrade.exit_date.desc())
        .limit(ROLLING_TRADE_WINDOW)
        .all()
    )
    if not trades:
        return None
    wins = sum(1 for t in trades if (t.gross_pnl or 0) > 0)
    return wins / len(trades)


def _regime_fit_score(db: Session, symbol: str) -> Optional[float]:
    """
    0..1 score: does the symbol have a promoted/active strategy whose
    allowed_regimes includes the current market regime, with a validated
    positive Sharpe in that regime? Returns None if no promoted/active
    strategy trades this symbol yet.
    """
    import json
    current_regime = (
        db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
    )
    current_regime = current_regime[0] if current_regime else None
    if not current_regime:
        return None

    strategies = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["promoted", "active"]))
        .all()
    )
    if not strategies:
        return None

    regime_sharpe_col = {
        "BULL": "bull_sharpe", "BEAR": "bear_sharpe",
        "SIDEWAYS": "sideways_sharpe", "VOLATILE": "volatile_sharpe",
    }.get(current_regime)
    if not regime_sharpe_col:
        return None

    best = None
    for s in strategies:
        try:
            allowed = json.loads(s.allowed_regimes) if s.allowed_regimes else []
        except (ValueError, TypeError):
            allowed = []
        if current_regime not in allowed:
            continue
        sharpe = getattr(s, regime_sharpe_col, None)
        if sharpe is None:
            continue
        # Normalize: Sharpe 0 -> 0.5, Sharpe >=2 -> 1.0, Sharpe <=-2 -> 0.0
        score = max(0.0, min(1.0, 0.5 + sharpe / 4.0))
        if best is None or score > best:
            best = score
    return best


def _research_strength_score(db: Session, symbol: str) -> Optional[float]:
    """
    0..1 score from the most recent ResearchSynthesis for this symbol:
    positive bullish sentiment -> higher score. Returns None if no
    synthesis exists yet for this symbol (research_synthesizer hasn't run,
    or ran and found no source data).
    """
    row = (
        db.query(ResearchSynthesis)
        .filter(ResearchSynthesis.symbol == symbol)
        .order_by(ResearchSynthesis.synthesis_date.desc())
        .first()
    )
    if row is None:
        return None
    # sentiment_score is -1..1; map to 0..1, weighted by the LLM's own
    # confidence so a low-confidence bullish call doesn't score as strongly
    # as a high-confidence one.
    base = (row.sentiment_score + 1.0) / 2.0
    confidence = row.confidence if row.confidence is not None else 0.5
    return base * confidence + 0.5 * (1 - confidence)  # blends toward neutral (0.5) as confidence drops


def compute_monthly_allocation(db: Session, as_of_date: Optional[date] = None) -> dict:
    """
    Rank the 3 owned satellites by conviction and suggest a tilted split of
    the month's ₹700 budget. Returns per-symbol scores and components so the
    reasoning is inspectable, not just a black-box percentage.
    """
    as_of_date = as_of_date or date.today()

    per_symbol: dict[str, dict] = {}
    for symbol in SATELLITE_SYMBOLS:
        wr = _live_win_rate_score(db, symbol)
        regime = _regime_fit_score(db, symbol)
        research = _research_strength_score(db, symbol)

        components = {
            "live_win_rate": wr,
            "regime_fit": regime,
            "research_strength": research,
        }

        # Conviction is a weighted blend of whichever components have real
        # data; components with None (no data) are excluded from both the
        # weighted sum and the weight normalization, rather than being
        # silently treated as 0 (which would look like "proven bad" instead
        # of "unknown").
        weighted_sum = 0.0
        weight_total = 0.0
        if wr is not None:
            weighted_sum += wr * WEIGHT_LIVE_WIN_RATE
            weight_total += WEIGHT_LIVE_WIN_RATE
        if regime is not None:
            weighted_sum += regime * WEIGHT_REGIME_FIT
            weight_total += WEIGHT_REGIME_FIT
        if research is not None:
            weighted_sum += research * WEIGHT_RESEARCH_STRENGTH
            weight_total += WEIGHT_RESEARCH_STRENGTH

        conviction = (weighted_sum / weight_total) if weight_total > 0 else None

        per_symbol[symbol] = {
            "components": components,
            "conviction_score": conviction,
            "has_any_data": weight_total > 0,
        }

    scored = {s: v["conviction_score"] for s, v in per_symbol.items() if v["conviction_score"] is not None}

    if not scored:
        # No live trades, no promoted strategies, no research synthesis for
        # any of the 3 satellites — nothing to differentiate them on. An
        # equal split is the only honest suggestion; do not fabricate a tilt.
        allocation = {s: round(SATELLITE_MONTHLY_BUDGET_INR / len(SATELLITE_SYMBOLS), 2) for s in SATELLITE_SYMBOLS}
        return {
            "as_of_date": as_of_date.isoformat(),
            "monthly_budget_inr": SATELLITE_MONTHLY_BUDGET_INR,
            "allocation_inr": allocation,
            "per_symbol": per_symbol,
            "basis": "equal_split_no_data",
            "note": "No live trade history, promoted strategies, or research synthesis available for any "
                    "satellite yet — suggesting an equal split until real signal exists. "
                    "This is a suggestion, not advice; you decide.",
        }

    # Tilt proportionally to conviction score among symbols WITH data;
    # symbols with no data get the average of the scored symbols (neutral,
    # not punished for lacking history).
    avg_scored = sum(scored.values()) / len(scored)
    full_scores = {s: per_symbol[s]["conviction_score"] if per_symbol[s]["conviction_score"] is not None else avg_scored
                   for s in SATELLITE_SYMBOLS}
    total_score = sum(full_scores.values())
    allocation = {}
    if total_score > 0:
        for s in SATELLITE_SYMBOLS:
            allocation[s] = round(SATELLITE_MONTHLY_BUDGET_INR * full_scores[s] / total_score, 2)
    else:
        allocation = {s: round(SATELLITE_MONTHLY_BUDGET_INR / len(SATELLITE_SYMBOLS), 2) for s in SATELLITE_SYMBOLS}

    ranked = sorted(SATELLITE_SYMBOLS, key=lambda s: full_scores[s], reverse=True)

    return {
        "as_of_date": as_of_date.isoformat(),
        "monthly_budget_inr": SATELLITE_MONTHLY_BUDGET_INR,
        "allocation_inr": allocation,
        "ranked_symbols": ranked,
        "per_symbol": per_symbol,
        "basis": "conviction_weighted",
        "note": "Suggestion, not advice — you decide. Ranks BEL/HDFCBANK/NTPC by live win-rate history, "
                "regime fit, and research synthesis strength; components without data are excluded from "
                "that symbol's score rather than treated as zero.",
    }

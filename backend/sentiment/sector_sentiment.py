"""
AQRTI Sector Sentiment
Aggregates company-level SentimentResult objects into a sector-level score.

Algorithm:
  1. Take all company sentiments for symbols in the sector
  2. Simple average (uniform weight — no market cap weighting yet)
  3. Compute sector velocity and acceleration as avg of company velocities
  4. Confidence = avg company confidence, penalised if < 3 stocks have data
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sentiment.company_sentiment import SentimentResult


def compute_sector_sentiment(
    sector_name: str,
    company_results: list[SentimentResult],
) -> Optional[SentimentResult]:
    """
    Aggregate company SentimentResults for one sector.
    Returns None if no company data is available.
    """
    if not company_results:
        return None

    n = len(company_results)

    avg_score        = sum(r.score       for r in company_results) / n
    avg_velocity     = sum(r.velocity    for r in company_results) / n
    avg_acceleration = sum(r.acceleration for r in company_results) / n
    avg_positive     = sum(r.positive_pct for r in company_results) / n
    avg_negative     = sum(r.negative_pct for r in company_results) / n
    avg_neutral      = sum(r.neutral_pct  for r in company_results) / n
    avg_confidence   = sum(r.confidence  for r in company_results) / n

    # Penalise confidence if sector coverage is thin (< 3 stocks)
    coverage_penalty = min(1.0, n / 3.0)
    sector_confidence = avg_confidence * coverage_penalty

    return SentimentResult(
        entity       = sector_name,
        entity_type  = "sector",
        score        = round(avg_score, 2),
        velocity     = round(avg_velocity, 4),
        acceleration = round(avg_acceleration, 4),
        confidence   = round(sector_confidence, 2),
        news_count   = sum(r.news_count for r in company_results),
        positive_pct = round(avg_positive, 1),
        negative_pct = round(avg_negative, 1),
        neutral_pct  = round(avg_neutral, 1),
        computed_at  = datetime.utcnow(),
    )


def compute_all_sector_sentiments(
    company_results: dict[str, SentimentResult],
    sector_map: dict[str, str],
) -> dict[str, SentimentResult]:
    """
    company_results : {symbol: SentimentResult}
    sector_map      : {symbol: sector_name}
    Returns         : {sector_name: SentimentResult}
    """
    sector_groups: dict[str, list[SentimentResult]] = {}

    for sym, result in company_results.items():
        sector = sector_map.get(sym, "Unknown")
        sector_groups.setdefault(sector, []).append(result)

    sector_sentiments: dict[str, SentimentResult] = {}
    for sector_name, results in sector_groups.items():
        s = compute_sector_sentiment(sector_name, results)
        if s is not None:
            sector_sentiments[sector_name] = s

    return sector_sentiments

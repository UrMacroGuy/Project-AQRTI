# SENTIMENT_ENGINE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI

## PURPOSE

Measure market psychology.

---

## SENTIMENT SOURCES

- News
- Social Media
- Analyst Reports
- Financial Media
- Forums

---

## SENTIMENT TYPES

- Positive
- Negative
- Neutral

---

## SENTIMENT METRICS

- Sentiment Score
- Sentiment Velocity
- Sentiment Acceleration
- Sentiment Persistence
- Virality
- Reach

---

## LEVEL SENTIMENTS

### COMPANY SENTIMENT
- **Example Ticker:** RELIANCE
- **Sentiment:** 82
- **Trend:** Improving

### SECTOR SENTIMENT
- **Example Sector:** IT Sector
- **Sentiment:** 74
- **Trend:** Stable

### MARKET SENTIMENT
- Fear
- Neutral
- Optimistic
- Euphoric

---

## OUTPUT

- Sentiment Score
- Confidence
- Direction
- Historical Comparison

---

## OBJECTIVE

Detect changes in narrative before price fully reacts.

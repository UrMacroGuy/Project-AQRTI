# NEWS_INTELLIGENCE_ENGINE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI

## PURPOSE

Convert unstructured news into machine-readable intelligence.

---

## DATA SOURCES

- Financial News
- Corporate Announcements
- Exchange Filings
- Economic Reports
- Industry Reports

---

## PIPELINE

```
       Collect
          ↓
        Clean
          ↓
     Deduplicate
          ↓
       Summarize
          ↓
   Entity Extraction
          ↓
  Sentiment Analysis
          ↓
    Impact Analysis
          ↓
        Store
```

---

## ENTITY EXTRACTION

Identify:
- Company
- Sector
- Industry
- People
- Products
- Events

---

## EVENT TYPES

- Earnings
- Acquisition
- Merger
- Buyback
- Management Change
- Large Order
- Regulatory Action
- Legal Issue
- Dividend

---

## IMPACT SCORE

- **Range:** 0-100
- Measures likely market impact.

---

## OUTPUT

- Company
- Event
- Sentiment
- Importance
- Expected Impact
- Confidence

---

## OBJECTIVE

Transform news into actionable signals.

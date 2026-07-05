# PATTERN_MATCHING_ENGINE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI

## PURPOSE

Find historical situations similar to current market conditions.

---

## CORE IDEA

- Markets repeat patterns.
- Not exactly.
- But often closely enough to extract probabilities.

---

## INPUTS

- Price Structure
- Volume Structure
- Sector State
- Market Regime
- Sentiment
- News Context
- Volatility

---

## PROCESS

```
   Current State
         ↓
  Feature Vector
         ↓
 Similarity Search
         ↓
Historical Matches
         ↓
 Outcome Analysis
         ↓
Probability Output
```

---

## SIMILARITY SCORE

- 0-100

---

## EXAMPLE

```
Current Pattern
       ↓
    Matches
```
- **March 2021:** 92%
- **August 2023:** 88%
- **January 2025:** 84%

---

## OUTPUT

- Expected Return
- Probability Distribution
- Historical Win Rate
- Risk Estimate

---

## KNOWLEDGE BASE

Stores:
- Pattern
- Outcome
- Confidence
- Context

---

## OBJECTIVE

Use history as an intelligence multiplier.

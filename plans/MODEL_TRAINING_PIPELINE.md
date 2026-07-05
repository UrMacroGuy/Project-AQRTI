# MODEL_TRAINING_PIPELINE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI

## PURPOSE

Train, validate, deploy, and continuously improve AQRTI models.

---

## TRAINING PHILOSOPHY

- Never train on future data.
- Never leak information.
- Every model must earn deployment.

---

## PIPELINE

```
      Raw Data
         ↓
 Feature Generation
         ↓
  Dataset Creation
         ↓
       Train
         ↓
      Validate
         ↓
 Walk Forward Test
         ↓
  Paper Validation
         ↓
       Deploy
```

---

## DATA SPLITS

- **Training:** 70%
- **Validation:** 15%
- **Testing:** 15%

---

## MODEL TYPES

- LightGBM
- XGBoost
- CatBoost
- Random Forest
- Meta Ranker

---

## FEATURE STORE

Stores:
- Price Features
- Volume Features
- Sentiment Features
- News Features
- Regime Features
- Sector Features

---

## RETRAINING

- **Daily:** Incremental Updates
- **Weekly:** Full Retraining
- **Monthly:** Architecture Review

---

## MODEL VERSIONING

- Model ID
- Training Date
- Features Used
- Metrics
- Status

---

## PROMOTION RULES

- Must beat production model.
- Must survive walk-forward validation.
- Must survive paper testing.

---

## OBJECTIVE

Continuously improve predictive quality while preventing overfitting.

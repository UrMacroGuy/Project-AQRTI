# LEARNING_ENGINE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI
## Self-Improvement & Knowledge Evolution System

Version: 1.0

---

## PURPOSE

The Learning Engine is responsible for ensuring AQRTI improves over time.

### Without learning:
- Models stagnate
- Strategies decay
- Performance deteriorates

### With learning:
- Mistakes become assets
- Failures become training data
- Confidence becomes calibrated
- System intelligence compounds

---

## LEARNING LOOP

```
     Prediction
         ↓
      Outcome
         ↓
      Analysis
         ↓
Root Cause Detection
         ↓
Knowledge Extraction
         ↓
    Model Update
         ↓
   Strategy Update
         ↓
Improved Future Decisions
```

---

## KNOWLEDGE TYPES

### Prediction Knowledge
Stores:
- Prediction
- Confidence
- Actual Result
- Error Magnitude

### Strategy Knowledge
Stores:
- Strategy Used
- Regime
- Result
- Drawdown
- Profitability

### Market Knowledge
Stores:
- Market State
- Sector State
- Volatility State
- Sentiment State

---

## FAILURE ANALYSIS

Every failure receives:
- Failure ID
- Category
- Severity
- Frequency
- Root Cause

### FAILURE CATEGORIES
- False Bullish
- False Bearish
- Regime Error
- Sentiment Error
- Data Error
- Execution Error
- Risk Error
- Overconfidence Error

---

## CONFIDENCE CALIBRATION

### Goal
83% confidence should be correct approximately 83% of the time.

### System Tracks
- Predicted Confidence
- Actual Accuracy
- Calibration Drift

---

## LEARNING DATABASE

- `knowledge_predictions`
- `knowledge_strategies`
- `knowledge_regimes`
- `knowledge_failures`
- `knowledge_patterns`
- `knowledge_adjustments`

---

## ADAPTATION RULES

- **If model accuracy drops:**  
  Reduce model weight.
- **If strategy performance drops:**  
  Reduce deployment priority.
- **If regime changes:**  
  Re-evaluate active strategies.

---

## KNOWLEDGE SCORE
*AQRTI tracks its own intelligence growth.*

### Metrics:
- Prediction Quality
- Strategy Quality
- Risk Quality
- Learning Quality

### Output:
- Knowledge Score (0-100)

---

## DAILY LEARNING PROCESS

```
Collect Outcomes
       ↓
 Analyze Errors
       ↓
Detect Patterns
       ↓
Update Knowledge
       ↓
 Adjust Models
       ↓
Adjust Strategies
       ↓
 Store Insights
```

---

## OBJECTIVE

The system should become harder to fool with every market cycle.

# MODEL_ARCHITECTURE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI
## Autonomous Quantitative Research & Trading Intelligence

Version: 1.0

---

## PURPOSE

The Model Architecture Layer is the intelligence core of AQRTI.

Its responsibility is not to predict exact stock prices.

Its responsibility is to answer:
- Which stocks have the highest probability of outperforming?
- Which opportunities have the best risk-adjusted returns?
- Which market conditions are currently active?
- Which strategies should be deployed?
- Which mistakes are recurring?
- How should the system adapt?

---

## CORE PHILOSOPHY

- AQRTI does not rely on a single model.
- Single models fail.
- AQRTI uses an ensemble intelligence system.
- Every prediction is produced through consensus.

---

## INTELLIGENCE PIPELINE

```
     Market Data
          ↓
  Feature Generation
          ↓
   Individual Models
          ↓
Meta Intelligence Layer
          ↓
    Risk Analysis
          ↓
  Confidence Analysis
          ↓
     Final Ranking
          ↓
   Strategy Selection
          ↓
   Prediction Output
```

---

## MODEL HIERARCHY

- **LEVEL 1:** Specialized Models
- **LEVEL 2:** Ensemble Layer
- **LEVEL 3:** Meta Intelligence Layer
- **LEVEL 4:** Risk Engine
- **LEVEL 5:** Final Decision Engine

---

## MODELS

### MODEL A: DIRECTION MODEL
#### Purpose
Predict market direction.

#### Output
- UP
- DOWN
- NEUTRAL

#### Target Horizon
- 3 Days
- 5 Days
- 10 Days
- 15 Days

#### Algorithms
- LightGBM
- XGBoost
- CatBoost

#### Output Example
- **Probability Up:** 78%
- **Probability Down:** 22%

---

### MODEL B: EXPECTED RETURN MODEL
#### Purpose
Estimate expected move.

#### Output Example
- **Expected Return:** +2.8%

#### Target
Regression Problem

#### Algorithms
- LightGBM Regressor
- CatBoost Regressor
- Random Forest Regressor

---

### MODEL C: VOLATILITY MODEL
#### Purpose
Predict future volatility.

#### Output
- LOW
- MEDIUM
- HIGH

#### Metrics
- ATR
- Historical Volatility
- Realized Volatility
- VIX Influence

---

### MODEL D: SENTIMENT MODEL
#### Purpose
Understand information flow.

#### Inputs
- News
- Corporate Announcements
- Financial Commentary
- Market Reports

#### Outputs
- Positive
- Negative
- Neutral

#### Additional Outputs
- Sentiment Strength
- Sentiment Velocity
- Sentiment Acceleration

---

### MODEL E: MARKET REGIME MODEL
#### Purpose
Identify current environment.

#### Possible Regimes
- Bull Market
- Bear Market
- Range Bound
- High Volatility
- Panic
- Recovery
- Sector Rotation

#### Importance
*No strategy is executed before regime classification.*

---

### MODEL F: SECTOR STRENGTH MODEL
#### Purpose
Determine strongest sectors.

#### Inputs
- Sector Returns
- Volume
- Breadth
- Relative Strength
- Momentum

#### Outputs
- Sector Ranking (0-100)

---

### MODEL G: RELATIVE STRENGTH MODEL
#### Purpose
Find leaders.

#### Questions
- Which stocks outperform NIFTY?
- Which stocks outperform their sector?
- Which stocks are attracting institutional money?

#### Output
- Relative Strength Score (0-100)

---

### MODEL H: EVENT IMPACT MODEL
#### Purpose
Estimate impact of events.

#### Events
- Earnings
- Mergers
- Acquisitions
- Buybacks
- Management Changes
- Large Orders
- Promoter Activity

#### Output
- Expected Event Impact (0-100)

---

### MODEL I: PATTERN MATCHING ENGINE
#### Purpose
Historical similarity search.

#### Process
```
Current Market State
         ↓
Search Historical Database
         ↓
 Find Similar Situations
         ↓
    Analyze Outcomes
         ↓
 Generate Probabilities
```

#### Output Example
- **Current Pattern resembles:** March 2021
- **Similarity:** 92%
- **Average Outcome:** +4.3%

---

### MODEL J: STRATEGY COMPATIBILITY MODEL
#### Purpose
Determine which strategy works now.

#### Strategies
- Momentum
- Breakout
- Mean Reversion
- Sector Rotation
- Sentiment
- Event Driven
- Hybrid

#### Output
- Strategy Ranking

---

## ENSEMBLE ENGINE
#### Purpose
Combine all model outputs.

#### Inputs
- Direction Model
- Expected Return Model
- Volatility Model
- Sentiment Model
- Regime Model
- Sector Model
- Pattern Model

#### Output
- Master Prediction

#### Example
- **Direction:** Bullish
- **Confidence:** 82%
- **Expected Return:** 3.1%
- **Risk:** Low

---

## META INTELLIGENCE LAYER
#### Purpose
Judge the judges.

#### Questions
- Which models are performing best?
- Which models are failing?
- Which model should receive more weight?

#### Example (Last 30 Days)
- **LightGBM:** 68% Accuracy
- **CatBoost:** 64% Accuracy
- **XGBoost:** 61% Accuracy
- **Result:** Increase LightGBM influence. Reduce XGBoost influence.

---

## CONFIDENCE ENGINE
#### Purpose
Determine trust level.

#### Inputs
- Agreement Between Models
- Historical Accuracy
- Regime Confidence
- Feature Quality
- Signal Strength

#### Output
- Confidence Score (0-100)

#### Confidence Categories
- **90-100:** Exceptional
- **80-89:** Strong
- **70-79:** Good
- **60-69:** Weak
- **Below 60:** Ignore

---

## LEARNING ENGINE
#### Purpose
Continuous improvement.

#### Every Prediction Stores:
- Features
- Prediction
- Confidence
- Actual Result
- Regime
- Sentiment
- News Context

#### Learning Questions
- Why was prediction wrong?
- Which features failed?
- Which model failed?
- Which strategy failed?
- Was risk underestimated?

#### Output
- Updated Weights
- Updated Rules
- Updated Features
- Updated Thresholds

---

## WALK-FORWARD VALIDATION
#### Purpose
Prevent overfitting.

#### Example
- **Train:** 2020-2023 | **Test:** 2024
- **Train:** 2021-2024 | **Test:** 2025
- **Train:** 2022-2025 | **Test:** 2026

*Only validated models are promoted.*

---

## STRATEGY SCORING SYSTEM

Every strategy receives a score (0-100) based on:
- Profit Factor
- Sharpe Ratio
- Sortino Ratio
- Win Rate
- Drawdown
- Expectancy
- Consistency
- Regime Robustness

---

## MODEL PROMOTION SYSTEM

```
Development
     ↓
  Testing
     ↓
 Validation
     ↓
Shadow Mode
     ↓
Paper Trading
     ↓
 Production
```
*No model may skip stages.*

---

## FAILURE ANALYSIS ENGINE
#### Purpose
Learn from mistakes.

#### Categories
- False Positive
- False Negative
- Sentiment Failure
- Regime Failure
- Data Failure
- Overconfidence Failure
- Risk Failure

*Each failure is stored permanently.*

---

## TARGET PERFORMANCE GOALS

- **Year 1:** Prediction Accuracy: 55-60%
- **Year 2:** Prediction Accuracy: 60-65%
- **Year 3:** Prediction Accuracy: 65-70%
- **Primary Goal:** Risk-Adjusted Returns (Not Accuracy)

---

## FINAL OUTPUT

For every stock, AQRTI produces:
- Symbol
- Rank
- Direction
- Confidence
- Expected Return
- Expected Risk
- Sector Score
- Sentiment Score
- Pattern Similarity
- Strategy Recommendation
- Position Size
- Reasoning

### Example
- **Symbol:** RELIANCE
- **Rank:** 1
- **Confidence:** 87%
- **Expected Return:** 3.4%
- **Risk:** Low
- **Recommended Strategy:** Momentum + Event Driven
- **Position Size:** 5%
- **Reason:** Strong sector trend, positive sentiment, earnings momentum, high historical similarity.

---

*AQRTI does not predict prices.*  
*AQRTI ranks opportunities.*  
*The highest-ranked opportunities become candidates for capital allocation.*

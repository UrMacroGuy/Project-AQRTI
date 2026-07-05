# DATA_ARCHITECTURE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI
## Autonomous Quantitative Research & Trading Intelligence

Version: 1.0

---

## PURPOSE

The Data Architecture Layer is the foundation of AQRTI.

Every prediction, strategy, risk calculation, learning cycle, and portfolio decision originates from this layer.

If data quality is poor:
- Predictions fail
- Strategies overfit
- Learning becomes useless
- Capital is lost

Therefore:
**Data quality takes priority over model complexity.**

---

## DATA PHILOSOPHY

AQRTI follows five principles.

### Principle 1
Store everything.
*Storage is cheaper than missing future signals.*

### Principle 2
Never overwrite raw data.
*Raw data is immutable.*

### Principle 3
Every derived feature must be reproducible.

### Principle 4
Every prediction must be traceable back to source data.

### Principle 5
Historical data is an asset.
*The database itself becomes a competitive advantage.*

---

## DATA FLOW

```
Raw Data
   ↓
Cleaning
   ↓
Normalization
   ↓
Feature Generation
   ↓
Storage
   ↓
Training
   ↓
Prediction
   ↓
Learning
   ↓
Feedback
   ↓
Improved Prediction
```

---

## DATA SOURCES

AQRTI will operate using multiple layers of information.

### LAYER 1: MARKET DATA
- Highest priority source.
- Collected daily.

#### Fields
- Date
- Open
- High
- Low
- Close
- Adjusted Close
- Volume
- VWAP
- Delivery Volume
- Trades Count
- Market Capitalization
- 52 Week High
- 52 Week Low

---

### LAYER 2: INDEX DATA

#### NIFTY
- Open
- High
- Low
- Close
- Volume
- Returns

#### BANKNIFTY
- Open
- High
- Low
- Close
- Volume
- Returns

#### SECTOR INDICES
- IT
- BANK
- PHARMA
- AUTO
- FMCG
- METAL
- ENERGY
- REALTY
- MEDIA
- PSU
- PRIVATE BANK
- CONSUMPTION

---

### LAYER 3: CORPORATE EVENTS
- Quarterly Results
- Dividend Announcements
- Bonus Issues
- Stock Splits
- Management Changes
- Acquisitions
- Mergers
- Board Meetings
- Share Buybacks
- Promoter Activity
- Block Deals
- Bulk Deals

---

### LAYER 4: NEWS DATA
- Headline
- Source
- Published Time
- Company Mentioned
- Sector Mentioned
- Importance Score
- Sentiment Score
- Impact Score
- Summary

---

### LAYER 5: SENTIMENT DATA

#### Source
- News
- Social Media
- Analyst Commentary
- Market Commentary
- Forums
- Financial Media

#### Fields
- Positive Score
- Negative Score
- Neutral Score
- Confidence
- Virality
- Reach
- Velocity

---

### LAYER 6: DERIVATIVES DATA
- Open Interest
- OI Change
- Put Call Ratio
- Max Pain
- Call Build Up
- Put Build Up
- Long Build Up
- Short Build Up
- Long Unwinding
- Short Covering

---

### LAYER 7: MACRO DATA
- Repo Rate
- Inflation
- GDP
- USDINR
- Crude Oil
- Gold
- Bond Yields
- VIX
- Global Indices

---

## DATABASE STRUCTURE

### Database Engine
- SQLite Initially
- PostgreSQL Later

### TABLES

#### stocks
- id
- symbol
- name
- sector
- industry
- market_cap
- listing_date
- nifty_member
- active

#### daily_prices
- id
- symbol
- date
- open
- high
- low
- close
- volume
- delivery_volume
- vwap
- returns

#### index_data
- id
- index_name
- date
- open
- high
- low
- close
- returns

#### news_events
- id
- timestamp
- headline
- summary
- source
- company
- sector
- sentiment
- impact_score
- importance_score
- url

#### sentiment_records
- id
- timestamp
- entity
- source
- positive
- negative
- neutral
- confidence
- virality

#### corporate_events
- id
- company
- event_type
- announcement_date
- event_date
- details
- impact_score

#### options_data
- id
- symbol
- date
- open_interest
- oi_change
- put_call_ratio
- max_pain

#### predictions
- id
- date
- symbol
- prediction
- confidence
- expected_return
- actual_return
- success

#### trades
- id
- symbol
- entry_date
- exit_date
- entry_price
- exit_price
- position_size
- profit_loss
- strategy

#### mistakes
- id
- trade_id
- prediction_id
- root_cause
- pattern_detected
- resolved

---

## FEATURE ENGINEERING
**Target:** 300+ Features

### PRICE FEATURES
- Daily Return
- Weekly Return
- Monthly Return
- Gap Up
- Gap Down
- Momentum
- Relative Strength
- Trend Strength
- Breakout Distance
- Support Distance
- Resistance Distance
- ATR
- RSI
- MACD
- Bollinger Width
- ADX
- ROC
- CCI
- Stochastic
- Williams %R

### VOLUME FEATURES
- Volume Change
- Volume Ratio
- Volume Spike
- Delivery Ratio
- Accumulation Score
- Distribution Score

### VOLATILITY FEATURES
- ATR
- Rolling Volatility
- Annualized Volatility
- Intraday Range
- Volatility Expansion
- Volatility Contraction

### MARKET FEATURES
- NIFTY Trend
- BankNifty Trend
- Sector Strength
- Breadth
- Advance Decline
- Market Regime

### NEWS FEATURES
- Headline Sentiment
- Article Sentiment
- News Frequency
- News Velocity
- Positive News Count
- Negative News Count

### SENTIMENT FEATURES
- Sentiment Score
- Sentiment Change
- Social Buzz
- Sentiment Velocity
- Sentiment Acceleration

### CORPORATE FEATURES
- Earnings Surprise
- Dividend Yield
- Buyback Signal
- Management Change Signal
- Promoter Activity Score

---

## LEARNING DATASET
*Every prediction becomes training data.*

### Store
- Input Features
- Prediction
- Confidence
- Outcome
- Error
- Market Regime
- News Context
- Sentiment Context
- Strategy Used

---

## DATA RETENTION

| Data Type | Retention Policy |
| --- | --- |
| **Raw Data** | Never Delete |
| **Processed Data** | Never Delete |
| **Predictions** | Never Delete |
| **Trades** | Never Delete |
| **Mistakes** | Never Delete |

---

## DAILY INGESTION PIPELINE

```
Step 1: Download Market Data
               ↓
Step 2: Download News
               ↓
Step 3: Download Sentiment
               ↓
Step 4: Normalize
               ↓
Step 5: Store
               ↓
Step 6: Generate Features
               ↓
Step 7: Train Models
               ↓
Step 8: Generate Predictions
               ↓
Step 9: Store Outcomes
               ↓
Step 10: Learn
```

---

## FUTURE SCALE TARGET

- **Year 1:** 500 Stocks
- **5 Years:** Millions of Records
- **Target Database Size:** 5GB - 20GB

---

This database becomes AQRTI's primary moat.

*Models can be replaced.*  
*Strategies can be replaced.*  
*The historical intelligence repository cannot.*

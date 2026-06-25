# AQRTI Intelligence Terminal — User Guide
### For someone new to the stock market

> **Last updated: 2026-06-25**
> Current state: Intelligence Score 71.5 · Regime SIDEWAYS · 4,087 strategies · 847 promoted · 7 agents healthy

---

## What is AQRTI?

AQRTI is an AI-powered stock market intelligence system built for the Indian market (NSE/BSE). Think of it as having a team of analysts working around the clock — reading news, studying charts, running backtests, tracking hundreds of stocks — and then summarising everything into a clean dashboard you can act on.

You don't need to know how to code. You don't need to understand machine learning. You just need to understand the basics of what the tool tells you and why it matters.

---

## Before You Start: Stock Market Basics

**What is the stock market?**
A stock market is a place where people buy and sell "shares" of companies. When you own a share of a company, you own a tiny piece of it. If the company does well, your share is worth more. If it does badly, it's worth less.

In India, the main stock exchange is the **NSE (National Stock Exchange)**. The most important index is **Nifty 50** — it tracks the 50 biggest companies and is used as a health indicator for the entire market.

**Key terms you'll see in AQRTI:**

| Term | What it means |
|------|---------------|
| **Bullish** | Expecting the price to go UP |
| **Bearish** | Expecting the price to go DOWN |
| **Confidence %** | How sure the AI is about its prediction (higher = more sure) |
| **Expected Return** | How much profit the AI expects in the coming days |
| **Sharpe Ratio** | Quality of returns relative to risk (above 1.0 is good, above 2.0 is great) |
| **Drawdown** | How much a portfolio dropped from its peak (lower is better) |
| **Regime** | The overall market mood: BULL, BEAR, SIDEWAYS, VOLATILE, RECOVERY |
| **VIX** | Market fear index — high VIX = high fear/uncertainty |

---

## Getting Started: The Dashboard Tour

When you open AQRTI, you land on the **Overview** page. Here's a quick tour of every section:

---

### 1. Overview (Home Page)
**What to look at first:**
- **Portfolio Value** — your paper trading portfolio's current worth (starts at ₹1,00,000)
- **Daily P&L** — today's profit or loss
- **Market Regime** — shown in the top bar. If it says BULL, conditions are good. BEAR means caution.
- **Top Predictions** — the stocks AQRTI is most confident about today

> **What to do:** Check the regime and top predictions every morning. If regime is BULL or RECOVERY, look for bullish opportunities. If BEAR or VOLATILE, be cautious.

---

### 2. Market Intelligence
**What it shows:** Live market data for Nifty 50, Bank Nifty, VIX, USD/INR, crude oil, gold.

- **Market Breadth** — what % of stocks are going up today. Above 60% = healthy market
- **A/D Ratio** — Advances vs Declines. Above 1 = more stocks rising than falling

> **What to do:** If breadth is above 65% and VIX is below 15, the market is in a good mood. Good time to look for trades.

---

### 3. Opportunity Rankings
**What it shows:** The best trade ideas for today, ranked by overall score.

Each opportunity shows:
- **Symbol** — the stock ticker (e.g., RELIANCE, HDFCBANK)
- **Confidence** — AI confidence in the prediction
- **Expected Return** — estimated % gain
- **Risk Level** — Low / Medium / High
- **Strategy** — what type of trading pattern is being used

> **What to do:** Focus on opportunities with confidence above 75% and Low/Medium risk. These are AQRTI's strongest signals.

---

### 4. News Intelligence
**What it shows:** Real news articles about stocks, scored by impact and sentiment.

- **Impact Score** (0-100) — how much this news matters. Above 75 = critical
- **Sentiment** — Positive / Negative / Neutral
- **High Impact Feed** — only the most important news

> **What to do:** If a stock in your portfolio has high-impact negative news, that's a warning. Positive news on an opportunity you're watching can increase confidence.

---

### 5. Sentiment Center
**What it shows:** How the market and individual companies "feel" right now, based on news analysis.

- **Market Score** — 0 to 100. Below 40 = fear, above 60 = greed
- **Company Sentiment** — which stocks have positive vs negative news flow
- **Sector Map** — which sectors are getting good/bad press

> **What to do:** Stocks with high positive sentiment (above 65) and good fundamentals are strong candidates. Avoid stocks with sentiment in the red.

---

### 6. Strategy Lab
**What it shows:** All the trading strategies AQRTI has discovered through backtesting.

- **Leaderboard** — strategies ranked by fitness score (combination of returns, Sharpe, drawdown)
- **Promoted strategies** — ones AQRTI trusts enough to use for live paper trading
- **Strategy Trades** — click any strategy to see every trade it made in backtests
- **Replay** — watch the strategy's entire backtest history play out as an animation

> **What to do:** Look at the top strategy. Check its win rate (should be above 50%) and Sharpe ratio (above 1.0). The "Replay Backtest" button lets you watch how the strategy performed trade by trade.

---

### 7. Model Center
**What it shows:** The AI models that make predictions.

AQRTI uses several machine learning models (CatBoost, LightGBM, XGBoost) trained on years of Indian market data.

- **Direction Accuracy** — how often the model correctly predicts if a stock will go up or down
- **AUC Score** — 0.5 means random guessing, 0.88 means very accurate
- **Walk-Forward Folds** — how many times the model was tested on out-of-sample data (real-world simulation)

> **What to do:** If the best model's accuracy is above 65%, AQRTI's predictions are reliable. If below 60%, treat signals with extra caution.

---

### 8. Learning Center
**What it shows:** How well AQRTI is learning over time.

- **Intelligence Score** (0-100) — AQRTI's overall learning quality. 70+ is good
- **Failure Analysis** — what predictions failed and why
- **Lessons** — rules AQRTI has learned ("Don't trade VOLATILE regime breakouts")
- **Calibration** — how honest the confidence scores are (well-calibrated = confidence matches actual accuracy)

> **What to do:** If the intelligence score is growing, AQRTI is improving. Review recent failures — they show you market conditions where the AI struggled.

---

### 9. Research Ops (Agents)
**What it shows:** 7 AI research agents working on your behalf:

| Agent | What it does |
|-------|--------------|
| Market Research | Analyses macro conditions |
| Pattern Research | Finds recurring price patterns |
| Strategy Research | Discovers and tests new trading strategies |
| Model Research | Evaluates AI model performance |
| News Research | Reads and scores news articles |
| Risk Research | Assesses portfolio risk |
| CRO (Chief Research Officer) | Synthesises everything into a daily brief |

- **Daily Brief** — the CRO's summary of the day: best opportunities, warnings, what AQRTI learned

> **What to do:** Read the Daily Brief every morning. It's the single most useful output from AQRTI.

---

### 10. Paper Trading
**What it shows:** A virtual ₹1,00,000 portfolio that AQRTI manages using its own predictions.

This is "paper trading" — real market data, fake money. It's how you test if AQRTI's ideas actually work before risking real money.

- **Open Positions** — stocks currently held, with entry price and current P&L
- **Equity Curve** — how the portfolio has grown over time
- **Trade History** — every closed trade with actual results
- **Analytics** — win rate, Sharpe ratio, max drawdown

**How it works:**
1. Every day after market close (3:30 PM IST), AQRTI runs its predictions
2. It picks the best stocks based on the best-performing strategy
3. It decides how much to invest in each (based on confidence)
4. It opens/closes positions automatically

> **What to do:** Compare the portfolio's win rate to 50% (random). If AQRTI is hitting 55%+, its edge is real. Watch the Sharpe ratio — above 1.0 means it's earning returns efficiently.

---

### 11. Risk Center
**What it shows:** Risk metrics for the current portfolio.

- **Exposure %** — how much of the portfolio is in stocks (vs cash)
- **VaR (Value at Risk)** — the maximum expected loss on a bad day
- **Max Drawdown** — biggest drop from the portfolio's peak
- **Sector Exposure** — which industries you're concentrated in
- **Circuit Breakers** — automatic safety rules (daily -3%, weekly -6%, monthly -12%)

> **What to do:** If exposure is above 80%, the portfolio is fully deployed — AQRTI is very confident. If circuit breakers are close to triggering, be careful. Never let max drawdown exceed 15% — that's a sign something is wrong.

---

### 12. Intelligence Vault
**What it shows:** AQRTI's memory — archived snapshots of past market states, portfolio values, research records.

- **Replay** — enter any past date to see what AQRTI knew on that day: market regime, portfolio, active strategies
- **Research Records** — all research AQRTI has ever conducted
- **Backups** — daily backups of the entire database

> **What to do:** Use the date replay to understand how AQRTI behaved during different market conditions (e.g., what did it do during a market crash?).

---

### 13. Intelligence Lab
**What it shows:** The advanced engine that drives AQRTI's self-improvement.

- **Regime Datasets** — labelled market history used to train the AI
- **Meta-Learning Insights** — patterns AQRTI found in its own failures
- **Feature Proposals** — new market signals AQRTI wants to add
- **Model/Strategy Memory** — what the AI has learned about each stock and strategy
- **Intelligence Pipeline** — the 12-step daily process (run manually or triggered automatically)

> **What to do:** You mostly don't need to touch this. But if you want to force a full intelligence refresh, click "Run Intelligence Pipeline". It rebuilds datasets, retrains models, and updates all insights.

---

### 14. Data Intelligence
**What it shows:** The quality and freshness of all the data AQRTI uses.

- **Data Quality Score** — how complete and accurate today's data is
- **FII/DII Activity** — how foreign and domestic institutional investors are moving money
- **Options Intelligence** — PCR (Put-Call Ratio), max pain levels for Nifty options
- **Earnings Calendar** — upcoming corporate results that could move stocks
- **Market Breadth** — sector-level advance/decline data

> **What to do:** If data quality is below 70%, today's predictions may be less reliable. If FII are selling heavily (negative), market might face headwinds.

---

## The Daily Routine (5 Minutes a Day)

**Morning (9:00 AM):**
1. Open AQRTI → check Market Regime
2. Read the Daily Brief (Research Ops page)
3. Review today's Opportunity Rankings (top 5)
4. Check News Intelligence for any high-impact news on your watchlist

**Evening (After 3:30 PM):**
1. Paper Trading page → see what positions were opened/closed today
2. Check the P&L on open positions
3. Learning Center → any new failures or lessons?

**Weekly:**
1. Strategy Lab → is the best strategy still performing well?
2. Model Center → is accuracy holding up?
3. Risk Center → are circuit breakers safe?

---

## Understanding AQRTI's Confidence

AQRTI gives every prediction a confidence score. Here's how to interpret it:

| Confidence | Meaning |
|------------|---------|
| **90%+** | Very high conviction. Rare. Strong signal. |
| **75–90%** | High confidence. Core trading opportunity. |
| **60–75%** | Moderate confidence. Worth watching. |
| **Below 60%** | Low confidence. AQRTI won't trade these. |

The minimum threshold for paper trading is set in the system (default: 60%). You'll only see trades above that level.

---

## What to Watch For (Warning Signs)

- **Regime = BEAR or VOLATILE** → AQRTI reduces position sizes automatically. Expect fewer trades.
- **Intelligence Score dropping** → AQRTI's predictions are getting less reliable. Don't act aggressively.
- **Win Rate below 45%** → Strategy may be failing. Check the Learning Center for recent failures.
- **Max Drawdown above 15%** → Portfolio is bleeding. Circuit breakers may trigger.
- **VIX above 20** → High market fear. AQRTI will be more conservative.
- **Circuit Breaker TRIGGERED** → Trading is automatically paused for safety.

---

## Things AQRTI Does NOT Do

- It does not execute real trades with real money — paper trading only
- It does not guarantee profits — all predictions can be wrong
- It does not predict events that haven't been publicly reported (no insider information)
- It does not replace your own judgment — use it as a second opinion, not the only opinion

---

## Glossary

| Term | Definition |
|------|-----------|
| **AUC** | Area Under Curve — model accuracy metric (0.5 = random, 1.0 = perfect) |
| **Backtest** | Testing a strategy on historical data to see how it would have performed |
| **Breakout** | When a stock moves above a resistance level — often signals a big move |
| **CAGR** | Compound Annual Growth Rate — annualised return |
| **Drawdown** | Drop from peak. 10% drawdown = portfolio fell 10% from its highest point |
| **ECE** | Expected Calibration Error — how well confidence scores match actual outcomes |
| **Equity Curve** | Chart showing portfolio value over time |
| **FII** | Foreign Institutional Investors (e.g., hedge funds, sovereign wealth funds) |
| **Fitness Score** | AQRTI's combined rating of a strategy: returns + consistency + risk |
| **Graveyard** | Strategies that failed and were retired — studied to avoid repeat mistakes |
| **Mark to Market** | Updating position values to current market prices |
| **P&L** | Profit & Loss |
| **PCR** | Put-Call Ratio — above 1.2 = bearish sentiment, below 0.8 = bullish |
| **Regime** | Market condition classification: BULL, BEAR, SIDEWAYS, VOLATILE, RECOVERY |
| **Rebalance** | Adjusting the portfolio — closing some positions, opening others |
| **Sharpe Ratio** | Return per unit of risk. Above 1.0 = good, above 2.0 = excellent |
| **Stop Loss** | The price at which a position is automatically closed to limit losses (default: 8% below entry) |
| **VaR** | Value at Risk — worst expected daily loss |
| **Walk-Forward** | Testing a model by training on past data and testing on future data (more rigorous than simple backtest) |
| **Win Rate** | % of trades that were profitable |

---

*AQRTI is a research and paper-trading tool. It does not constitute financial advice. Past performance does not guarantee future results.*

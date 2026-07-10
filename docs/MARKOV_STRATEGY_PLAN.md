# Markov & Regime-Switching Strategy Implementation Plan

## 1. Strategy Types

Three Markov-powered strategy variants to implement, in increasing complexity:

### 1.1 Observable Markov Chain (MC) — Regime Filter
- **States:** Bull / Bear / Sideways defined by trailing N-day return (e.g. N=20, threshold=5%)
- **Signal:** Build 3×3 transition matrix from daily labels → stationary distribution → signal = P(Bull) − P(Bear)
- **Use case:** A regime-aware entry gate for existing strategy DSL conditions (`regime_bias > 0.3`)
- **Where it fits:** New family `markov_regime` in `strategy_generator._FAMILY_WEIGHTS`

### 1.2 Hidden Markov Model (HMM) — Latent Regime Detection
- **States:** 2-4 latent regimes estimated via Baum-Welch (EM) on daily returns + volatility features
- **Signal:** Smoothed regime probability via `hmmlearn.GaussianHMM` → trade long when regime-0 prob > 0.65
- **Use case:** A standalone entry condition that replaces the current KMeans-based regime discovery
- **Where it fits:** New `intelligence/markov_regime.py` module, new `markov_hmm` family

### 1.3 Markov-Switching Pairs Trading
- **States:** 2-regime Markov process on cointegrated pair spread (mean + volatility regime)
- **Signal:** Enter when spread deviates > δ·σ within current regime, exit on reversion
- **Use case:** New pairs-trading strategy family built on existing `cointegration` detection
- **Where it fits:** New `strategies/markov_pairs.py`, new `markov_pairs` family

---

## 2. Integration Points

All three variants plug into the existing pipeline at:

### 2.1 Feature Layer (`backend/features/`)
- Add `markov_regime_features.py` — per-symbol/sector/NIFTY features:
  - `regime_state` (BULL=2, SIDEWAYS=1, BEAR=0) — from day's NIFTY 20d return
  - `regime_bias` — signal from transition matrix stationary distribution
  - `regime_persistence` — diagonal entry of transition matrix (stickiness)
  - `hmm_regime_class` — decoded latent regime (0..K-1) from per-day HMM inference
  - `hmm_confidence` — posterior probability of most likely regime
- Register all in `feature_registry.py` under new category `"markov"`

### 2.2 Regime Detection (`backend/intelligence/`)
- Replace KMeans-based `regime_discovery.py` with HMM for primary regime classification
- Keep existing regime-writing pipeline (`market_sentiment.determine_regime()` + `MarketRegime`) intact
- Add `backend/intelligence/markov_regime.py`:
  - `MarkovRegimeDetector` — fits `hmmlearn.GaussianHMM` on NIFTY returns + volatility
  - `fit()` — EM on rolling 252-day window, refit weekly
  - `decode()` — Viterbi to assign latent regime label to each day
  - `smooth()` — forward-backward for regime probabilities
  - `predict_proba()` — one-step-ahead regime distribution
  - `transition_matrix` — exposes 3×3 or 4×4 transition matrix

### 2.3 Strategy Generator (`backend/strategies/`)
Three new families added to `_FAMILY_WEIGHTS` in `strategy_generator.py`:

| Family | Weight | Entry conditions | Exit | SL | Confidence |
|--------|--------|-----------------|------|----|-----|
| `markov_regime` | 0.06 | regime_bias > r (r∼U[0.15,0.45]) + regime_state ∈ allowed | return_5d ≤ 0 | 3-7% ATR | 0.30-0.55 |
| `markov_hmm` | 0.05 | hmm_regime_class ∈ allowed + hmm_confidence > c (c∼U[0.50,0.80]) + rsi_14 ∈ [40,65] | return_5d ≤ 0 | 3-6% ATR | 0.35-0.55 |
| `markov_pairs` | 0.04 | spread_zscore < -z_entry (z∼U[1.5,2.5]) + hmm_regime_class=0 | spread_zscore > -0.5 | 2× spread_σ | 0.40-0.55 |

### 2.4 Strategy DSL (`backend/strategies/strategy_dsl.py`)
Add new condition types:
- `RegimeBias(r)` — evaluates `regime_bias >= r`
- `RegimeState(s)` — evaluates `regime_state == s`
- `HMMRegimeClass(k)` — evaluates `hmm_regime_class == k`
- `HMMConfidence(c)` — evaluates `hmm_confidence >= c`
- `SpreadZScore(z)` — evaluates absolute `spread_zscore >= z`

### 2.5 Mutation Engine (`backend/strategies/mutation_engine.py`)
Add mutation operators for Markov-specific parameters:
- Threshold nudge: `r ± 0.05`, `c ± 0.05`, `z_entry ± 0.2`
- Regime filter toggle: swap `allowed_regimes` subsets
- HMM state constraint: shift target `hmm_regime_class` by ±1

---

## 3. Schema Changes (`backend/aqrti/database/models.py`)

**New tables:**

```sql
-- HMM model artifacts (one row per fit, versioned)
CREATE TABLE hmm_models (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fit_date        DATE NOT NULL,
    n_states        INTEGER NOT NULL DEFAULT 3,
    window_days     INTEGER NOT NULL DEFAULT 252,
    means_json      TEXT NOT NULL,          -- JSON array of state means
    covars_json     TEXT NOT NULL,           -- JSON array of state covariances
    transmat_json   TEXT NOT NULL,           -- JSON transition matrix
    startprob_json  TEXT NOT NULL,           -- JSON initial state probabilities
    version         INTEGER NOT NULL DEFAULT 1,
    is_active       BOOLEAN DEFAULT TRUE,
    trained_at      DATETIME DEFAULT (datetime('now'))
);

-- Daily HMM regime assignments
CREATE TABLE hmm_regime_daily (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE NOT NULL UNIQUE,
    regime_class    INTEGER NOT NULL,        -- 0..K-1
    confidence_pct  REAL NOT NULL,           -- 0-100
    state_label     TEXT,                    -- "BULL"|"BEAR"|"SIDEWAYS" mapped from class
    created_at      DATETIME DEFAULT (datetime('now'))
);
```

**New columns in `strategies_v2` (add migration):**
- `regime_compatibility` REAL — what fraction of backtest dates were in regimes where this strategy was designed to trade (0-1)
- `regime_switch_count` INTEGER — how many times a promoted strategy triggered a regime-based exit

---

## 4. Backtester Changes (`backend/strategies/strategy_backtester.py`)

- No new code needed: the Markov conditions are just new DSL condition types. The DSL evaluator (`evaluate()`) already returns bool for entry gates.
- However, the backtester's `_regime_on` key must expand to accept `hmm_regime_class` in addition to `MarketRegime.regime`. Add a fallback: if `hmm_regime_daily` table has a row for `today`, prefer that regime to `MarketRegime` for entry/exit decisions controlled by Markov conditions.
- The new `regime_compatibility` metric: ratio of days where the strategy was in a „tradeable“ regime (from `allowed_regimes` or `hmm_regime_class` match) vs total backtest days. Computed post-backtest in `fitness_engine`.

---

## 5. Arena & Fitness (`backend/strategies/arena_engine.py`, `fitness_engine.py`)

- Arena needs no change — new families enter via `strategy_generator` just like any other family.
- Fitness engine: regime-adaptability dimension (`regime_adaptability_score`) already exists. No change needed; Markov families will score naturally on their ability to perform across regimes.
- Add a _regime_stability_ bonus: strategies whose `regime_compatibility > 0.8` (trade in many regimes) get a +0.05 fitness multiplier, rewarding robustness.

---

## 6. Training Pipeline (`backend/intelligence/markov_regime.py`)

### 6.1 Initial Fit
- On boot: load last 252 trading days of NIFTY daily returns + volatility from IndexData
- Fit `GaussianHMM(n_components={2,3,4}, covariance_type="diag", n_iter=1000)` for each K
- Select best K via BIC (Bayesian Information Criterion)
- Store model as pickle in `ml_models/markov/` and register in `hmm_models`
- Decode all 252 days → insert/update `hmm_regime_daily`

### 6.2 Refit Schedule
- Weekly on Saturday maintenance run (or daily if `AQRTI_LITE_MODE=1` skips it)
- Rolling window: train = previous 504 days (2 yrs), keep the last `n_states` from prior fit as starting guess
- Re-run BIC selection every 4th refit (monthly) to detect structural changes needing more/fewer states
- Version bump in `hmm_models`; old versions stay active until replaced

### 6.3 Integration with Daily Pipeline
- After `boot_step_5` (feat generation), before `boot_step_6` (regime discovery):
  - `MarkovRegimeDetector.decode(today.returns, today.vol)` → assign today's regime
  - Write to `hmm_regime_daily`
- Feature generator reads `hmm_regime_daily` for the date slice (point-in-time correct by construction)

---

## 7. Feature Generation (`backend/features/markov_regime_features.py`)

For each date `d` in each symbol's history:
- Read `hmm_regime_daily` row at `<= d` (most recent regime assignment)
- Compute `regime_state` from NIFTY 20d return at `d`
- Compute transition matrix from `hmm_regime_daily` rows in `[d-504, d]`
- Compute `regime_bias` = `stationary_distribution[2] - stationary_distribution[0]` (Bull prob − Bear prob)
- Write as per-date feature vector in `FeatureValue`

**Point-in-time correctness rules:**
- `hmm_regime_daily` is written daily, so `date <= d` correctly gives the regime known at end of day `d`.
- For the transition matrix: include rows `[d-504, d]` inclusive; the matrix at `d` is computable from elapsed regimes only — no future leak.
- The HMM decode for day `d` is available starting from `d+1` (next day's boot step). Feature computation for day `d` runs after the decode for `d` is done — order matter.

---

## 8. Strategy Generation — DSL Candidates

### 8.1 Markov Regime Filter (`markov_regime`)
```
entry:
  regime_bias > 0.30
  regime_state in (BULL)
exit: return_5d <= 0
sl: 5% ATR
conf: 0.45
holding: 5-15 days
```

### 8.2 HMM Adaptive (`markov_hmm`)
```
entry:
  hmm_regime_class in (0, 1)
  hmm_confidence > 0.60
  rsi_14 between 40 and 60
exit: return_5d <= 0
sl: 4% ATR
conf: 0.40
holding: 3-12 days
```

### 8.3 Regime-Defensive (`markov_hmm`)
```
entry:
  hmm_regime_class in (0)          # only trade in calm regimes
  hmm_confidence > 0.70
  return_20d > -0.05
exit: hmm_regime_class != 0 or return_5d <= -0.03
sl: 3% ATR
conf: 0.50
holding: 5-20 days
```

---

## 9. Implementation Order

| Step | File(s) | Dependencies | Effort |
|------|---------|-------------|--------|
| 1. Add `hmmlearn` to `requirements.txt` | — | None | 5 min |
| 2. Create schema: `hmm_models`, `hmm_regime_daily` | `models.py` + migration | Step 1 | 1 hr |
| 3. Implement `MarkovRegimeDetector` | `markov_regime.py` | Step 2 | 4 hr |
| 4. Integrate into boot pipeline (decode daily) | `app.py`, `scheduler.py` | Step 3 | 1 hr |
| 5. Add Markov feature functions | `markov_regime_features.py`, `feature_registry.py` | Step 4 | 3 hr |
| 6. Add DSL condition types | `strategy_dsl.py` | Step 5 | 1 hr |
| 7. Register new families in generator | `strategy_generator.py` | Step 6 | 30 min |
| 8. Add mutation operators for params | `mutation_engine.py` | Step 7 | 1 hr |
| 9. Verify backtester compatibility | `strategy_backtester.py` | Step 7 | 1 hr |
| 10. Walk-forward validation script | `scripts/walk_forward_markov.py` | Full stack | 3 hr |
| **Total** | | | **~16 hr** |

---

## 10. Walk-Forward Validation

Every Markov-strategy backtest must pass a dedicated walk-forward:

1. **Time splits:** 12 rolling folds, each: train=504 days, test=63 days (~1 quarter)
2. **Per fold:** Fit HMM on train window → generate features on train+test → generate strategies using train-only features → backtest on test window (with point-in-time features)
3. **Honest metric:** Only test-window P&L counts. Aggregate across all folds.
4. **Pass gate:** Walk-forward Sharpe ≥ 0.7 (vs the standard 1.0 baseline for normal backtests — the WFO bar is deliberately lower because WFO naturally produces worse metrics)
5. **Costs:** Full 0.28% NSE round-trip applied; same as standard backtests

The walk-forward re-estimates the HMM from scratch in each fold (no state-carryover), which is the most conservative approach. If this passes, the strategy is genuinely regime-adaptive, not fitting to a specific HMM fit.

---

## 11. Risk & Failure Modes

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| HMM overfits to noise, regimes flip too often | Regime persistence < 10 days average → stale/worthless signal | Floor on transition‑matrix diagonal entries (min 0.70) |
| HMM assigns all days to 1 regime | One column of transition matrix = 1.0, others = 0.0 | Enforce min covariance per state; reject degenerate fits |
| Markov entry too slow to react to flash crash | 20d return threshold misses regime shift for 2+ weeks | Add volatility-trigger fallback (Vix-like from option data or ATR spike) |
| New family gets zero candidates (C16 class) | Check `strategy_generation` logs for `"condition matches known-bad zone"` | Ensure Markov features are registered in `feature_registry` and have non‑null values in the universe |
| `hmm_regime_daily` has gaps on weekends/holidays | No row for date → feature generator returns NaN → fail-closed skip | Schedule `markov_regime.decode` daily even on holidays (re‑decode last close into existing regime) |

---

## 12. Testing Plan

- **Unit:** `MarkovRegimeDetector` fit/decode/predict with synthetic 2-regime data (shifted normal dist) — confirm decoded regime matches injected switching pattern
- **Integration:** Run `generate_candidates(n=50)` with `meta_state=None` — confirm `markov_regime` and `markov_hmm` candidates appear, have valid DSL entries with Markov conditions, and `_passes_prescreen` approves them
- **Backtest:** Select top-5 candidates from each family, run `backtest_and_update`, confirm:
  - Entry/exit dates align with regime transitions in the test period
  - `regime_compatibility` metric is computed and > 0
  - No NaN Sharpe, no degenerate trades
- **Walk-forward:** `scripts/walk_forward_markov.py` run — all 12 folds complete with test-window metrics

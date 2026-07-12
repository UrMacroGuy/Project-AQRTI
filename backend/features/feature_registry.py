"""
AQRTI Feature Registry
Single source of truth for all feature definitions.
Every feature has: name, category, version, description, formula, inputs, min_periods.
The registry seeds the feature_metadata table on first run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from sqlalchemy.orm import Session

from aqrti.database.models import FeatureMetadata
from aqrti.utils.logger import get_logger

log = get_logger("feature_registry")


@dataclass
class FeatureDef:
    name: str
    category: str          # price | volume | volatility | trend | market
    description: str
    formula: str
    inputs: List[str]
    min_periods: int
    version: int = 1
    output_type: str = "float"


# ══════════════════════════════════════════════════════════════
# FEATURE CATALOG
# ══════════════════════════════════════════════════════════════
FEATURE_CATALOG: List[FeatureDef] = [

    # ── PRICE FEATURES ───────────────────────────────────────
    FeatureDef("return_1d",               "price", "1-day simple return (%)",
               "((close_t / close_t-1) - 1) * 100", ["close"], 2),
    FeatureDef("return_5d",               "price", "5-day simple return (%)",
               "((close_t / close_t-5) - 1) * 100", ["close"], 6),
    FeatureDef("return_21d",              "price", "21-day simple return (%)",
               "((close_t / close_t-21) - 1) * 100", ["close"], 22),
    FeatureDef("return_63d",              "price", "63-day simple return (%)",
               "((close_t / close_t-63) - 1) * 100", ["close"], 64),
    FeatureDef("momentum_10d",            "price", "10-day price momentum (ROC)",
               "(close_t - close_t-10) / close_t-10 * 100", ["close"], 11),
    FeatureDef("momentum_20d",            "price", "20-day price momentum (ROC)",
               "(close_t - close_t-20) / close_t-20 * 100", ["close"], 21),
    FeatureDef("gap_open_pct",            "price", "Gap at open vs prior close (%)",
               "(open_t - close_t-1) / close_t-1 * 100", ["open", "close"], 2),
    FeatureDef("breakout_distance_52w",   "price", "Distance from 52-week high (%)",
               "(close_t - max(close, 252)) / max(close, 252) * 100", ["close"], 252),
    FeatureDef("support_distance_20d",    "price", "Distance above 20-day low (%)",
               "(close_t - min(close, 20)) / min(close, 20) * 100", ["low"], 20),
    FeatureDef("resistance_distance_20d", "price", "Distance below 20-day high (%)",
               "(max(high, 20) - close_t) / close_t * 100", ["high", "close"], 20),
    FeatureDef("price_position_52w",      "price", "Price position within 52-week range (0-1)",
               "(close - min_52w) / (max_52w - min_52w)", ["close"], 252),
    FeatureDef("relative_strength_nifty_21d", "price", "Stock return vs NIFTY50 over 21 days",
               "return_21d_stock - return_21d_nifty", ["close"], 22),

    # ── VOLUME FEATURES ──────────────────────────────────────
    FeatureDef("volume_ratio_5d",    "volume", "Volume / 5-day avg volume",
               "volume_t / mean(volume, 5)", ["volume"], 5),
    FeatureDef("volume_ratio_20d",   "volume", "Volume / 20-day avg volume",
               "volume_t / mean(volume, 20)", ["volume"], 20),
    FeatureDef("relative_volume",    "volume", "Volume percentile rank vs 63-day window",
               "percentile_rank(volume_t, volume_63d)", ["volume"], 63),
    FeatureDef("volume_spike",       "volume", "1 if volume > 2x 20d avg, else 0",
               "1 if volume_ratio_20d > 2.0 else 0", ["volume"], 20, output_type="bool"),
    FeatureDef("accumulation_score_5d", "volume", "Days with close > open weighted by volume (5d)",
               "sum(volume[close>open], 5) / sum(volume, 5)", ["close", "open", "volume"], 5),
    FeatureDef("distribution_score_5d", "volume", "Days with close < open weighted by volume (5d)",
               "sum(volume[close<open], 5) / sum(volume, 5)", ["close", "open", "volume"], 5),
    FeatureDef("obv_slope_10d",      "volume", "On-Balance Volume 10-day linear regression slope",
               "linregress(obv, 10).slope / close", ["close", "volume"], 11),
    FeatureDef("delivery_ratio",     "volume", "Delivery volume / total volume",
               "delivery_volume / volume", ["volume", "delivery_volume"], 1),

    # ── VOLATILITY FEATURES ──────────────────────────────────
    FeatureDef("atr_14",            "volatility", "14-day Average True Range",
               "mean(TR, 14) where TR = max(high-low, |high-prev_close|, |low-prev_close|)",
               ["high", "low", "close"], 15),
    FeatureDef("atr_pct_14",        "volatility", "ATR as % of close price",
               "atr_14 / close * 100", ["high", "low", "close"], 15),
    FeatureDef("rolling_vol_10d",   "volatility", "10-day realised return volatility (annualised %)",
               "std(daily_return, 10) * sqrt(252)", ["close"], 11),
    FeatureDef("rolling_vol_21d",   "volatility", "21-day realised return volatility (annualised %)",
               "std(daily_return, 21) * sqrt(252)", ["close"], 22),
    FeatureDef("historical_vol_63d","volatility", "63-day historical volatility (annualised %)",
               "std(daily_return, 63) * sqrt(252)", ["close"], 64),
    FeatureDef("vol_expansion",     "volatility", "1 if 10d vol > 21d vol by >20%, else 0",
               "1 if rolling_vol_10d > rolling_vol_21d * 1.2 else 0",
               ["close"], 22, output_type="bool"),
    FeatureDef("vol_compression",   "volatility", "1 if 10d vol < 21d vol by >20%, else 0",
               "1 if rolling_vol_10d < rolling_vol_21d * 0.8 else 0",
               ["close"], 22, output_type="bool"),
    FeatureDef("beta_21d",          "volatility", "21-day rolling beta vs NIFTY50",
               "cov(stock_ret, nifty_ret, 21) / var(nifty_ret, 21)", ["close"], 22),

    # ── TREND FEATURES ───────────────────────────────────────
    FeatureDef("ema_9",             "trend", "9-day Exponential Moving Average",
               "EMA(close, span=9)", ["close"], 9),
    FeatureDef("ema_21",            "trend", "21-day Exponential Moving Average",
               "EMA(close, span=21)", ["close"], 21),
    FeatureDef("ema_50",            "trend", "50-day Exponential Moving Average",
               "EMA(close, span=50)", ["close"], 50),
    FeatureDef("ema_200",           "trend", "200-day Exponential Moving Average",
               "EMA(close, span=200)", ["close"], 200),
    FeatureDef("sma_20",            "trend", "20-day Simple Moving Average",
               "mean(close, 20)", ["close"], 20),
    FeatureDef("sma_50",            "trend", "50-day Simple Moving Average",
               "mean(close, 50)", ["close"], 50),
    FeatureDef("price_vs_ema21_pct","trend", "% deviation of close from EMA21",
               "(close - ema_21) / ema_21 * 100", ["close"], 21),
    FeatureDef("price_vs_ema50_pct","trend", "% deviation of close from EMA50",
               "(close - ema_50) / ema_50 * 100", ["close"], 50),
    FeatureDef("price_vs_ema200_pct","trend", "% deviation of close from EMA200",
               "(close - ema_200) / ema_200 * 100", ["close"], 200),
    FeatureDef("macd_line",         "trend", "MACD line (EMA12 - EMA26)",
               "EMA(close,12) - EMA(close,26)", ["close"], 26),
    FeatureDef("macd_signal",       "trend", "MACD signal line (EMA9 of MACD)",
               "EMA(macd_line, 9)", ["close"], 35),
    FeatureDef("macd_histogram",    "trend", "MACD histogram (macd_line - macd_signal)",
               "macd_line - macd_signal", ["close"], 35),
    FeatureDef("macd_crossover",    "trend", "1 bullish crossover, -1 bearish, 0 none",
               "sign(macd_histogram_t) != sign(macd_histogram_t-1)",
               ["close"], 35, output_type="int"),
    FeatureDef("rsi_14",            "trend", "14-day Relative Strength Index",
               "100 - 100/(1 + avg_gain_14/avg_loss_14)", ["close"], 15),
    FeatureDef("rsi_divergence",    "trend", "RSI divergence: price vs RSI direction mismatch",
               "sign(return_5d) != sign(rsi_14_change_5d)", ["close"], 20, output_type="bool"),
    FeatureDef("adx_14",            "trend", "14-day Average Directional Index",
               "EMA(|DI+ - DI-|/(DI+ + DI-), 14) * 100", ["high", "low", "close"], 28),
    FeatureDef("di_plus_minus",     "trend", "DI+ minus DI- (positive = uptrend)",
               "di_plus_14 - di_minus_14", ["high", "low", "close"], 15),
    FeatureDef("ma_20_slope",       "trend", "SMA20 5-bar slope as % change (RL momentum)",
               "(sma_20_now - sma_20_5bars_ago) / sma_20_5bars_ago * 100", ["close"], 25),
    FeatureDef("ma_50_slope",       "trend", "SMA50 5-bar slope as % change (RL momentum)",
               "(sma_50_now - sma_50_5bars_ago) / sma_50_5bars_ago * 100", ["close"], 55),
    FeatureDef("ma_spread",         "trend", "(SMA20 - SMA50) / SMA50 * 100 — golden cross proximity",
               "(sma_20 - sma_50) / sma_50 * 100", ["close"], 50),
    FeatureDef("close_ma20_diff",   "trend", "(close - SMA20) / SMA20 * 100 — price vs MA20",
               "(close - sma_20) / sma_20 * 100", ["close"], 20),
    FeatureDef("close_ma50_diff",   "trend", "(close - SMA50) / SMA50 * 100 — price vs MA50",
               "(close - sma_50) / sma_50 * 100", ["close"], 50),

    # ── MARKET / SECTOR FEATURES ─────────────────────────────
    FeatureDef("nifty_rs_21d",          "market", "Stock 21d return minus NIFTY 21d return",
               "stock_return_21d - nifty_return_21d", ["close"], 22),
    FeatureDef("nifty_beta_daily",      "market", "Daily beta vs NIFTY (21d rolling)",
               "cov(r_stock,r_nifty,21)/var(r_nifty,21)", ["close"], 22),
    FeatureDef("sector_rs_21d",         "market", "Stock 21d return minus sector avg 21d return",
               "stock_return_21d - sector_avg_return_21d", ["close"], 22),
    FeatureDef("sector_rank",           "market", "Percentile rank within sector (21d return)",
               "percentile_rank(return_21d, sector_peers)", ["close"], 22),
    FeatureDef("breadth_pct_above_ema50",  "market", "% of universe stocks above their EMA50",
               "count(close > ema_50) / universe_size", ["close"], 50),
    FeatureDef("breadth_pct_above_ema200", "market", "% of universe stocks above their EMA200",
               "count(close > ema_200) / universe_size", ["close"], 200),
    FeatureDef("nifty_return_5d",       "market", "NIFTY50 5-day return (%)",
               "((nifty_close_t / nifty_close_t-5) - 1) * 100", ["nifty_close"], 6),
    FeatureDef("nifty_return_21d",      "market", "NIFTY50 21-day return (%)",
               "((nifty_close_t / nifty_close_t-21) - 1) * 100", ["nifty_close"], 22),
    FeatureDef("sector_return_5d",      "market", "Sector avg 5-day return (%)",
               "mean(peer_return_5d)", ["close"], 6),
    FeatureDef("sector_return_21d",     "market", "Sector avg 21-day return (%)",
               "mean(peer_return_21d)", ["close"], 22),
    FeatureDef("peer_rank_return_21d",  "market", "Rank within sector by 21d return (1=best)",
               "rank(return_21d) within sector", ["close"], 22, output_type="int"),
    FeatureDef("peer_rank_vol",         "market", "Rank within sector by 21d vol (1=lowest)",
               "rank(rolling_vol_21d) within sector", ["close"], 22, output_type="int"),
    FeatureDef("relative_vol_vs_sector","market", "Stock 21d vol / sector avg 21d vol",
               "rolling_vol_21d / sector_avg_vol_21d", ["close"], 22),

    # ── FII/DII FLOW FEATURES (P1-A) ─────────────────────────
    FeatureDef("fii_net_1d",               "market", "FII net equity buy/sell today (crores)",
               "fii_gross_buy - fii_gross_sell", ["fii_dii_flows"], 1),
    FeatureDef("fii_net_5d",               "market", "5-day rolling FII net equity flow (crores)",
               "sum(fii_net_investment, 5d)", ["fii_dii_flows"], 5),
    FeatureDef("fii_net_20d",              "market", "20-day rolling FII net equity flow (crores)",
               "sum(fii_net_investment, 20d)", ["fii_dii_flows"], 20),
    FeatureDef("dii_net_1d",               "market", "DII net equity buy/sell today (crores)",
               "dii_gross_buy - dii_gross_sell", ["fii_dii_flows"], 1),
    FeatureDef("fii_dii_ratio",            "market", "5d FII net / |5d DII net| (signed, capped +-10)",
               "fii_net_5d / abs(dii_net_5d)", ["fii_dii_flows"], 5),
    FeatureDef("institutional_flow_signal","market", "Majority institutional signal: BULLISH=1, BEARISH=-1, NEUTRAL=0",
               "majority_vote(fii_signal, dii_signal)", ["fii_dii_flows"], 1),

    # ── PEER-MEAN PROPAGATION FEATURES (P2-A) ────────────────
    FeatureDef("peer_mean_momentum_10d",   "market", "Mean 10d momentum of top-10 correlation peers",
               "mean(peer_momentum_10d, top10_corr_peers)", ["close"], 11),
    FeatureDef("peer_mean_rsi_14",         "market", "Mean RSI14 of top-10 correlation peers",
               "mean(peer_rsi_14, top10_corr_peers)", ["close"], 15),
    FeatureDef("peer_mean_vol_21d",        "market", "Mean 21d vol of top-10 correlation peers",
               "mean(peer_rolling_vol_21d, top10_corr_peers)", ["close"], 22),

    # ── RESEARCH-DERIVED FEATURES (research_synthesis funnel) ─
    # LLM-derived, point-in-time joined from research_synthesis. Null when no
    # synthesis exists for the symbol as of date d — never fabricated.
    FeatureDef("research_sentiment",       "research", "Most recent research_synthesis.sentiment_score (-1..1), lookback <=5d",
               "research_synthesis.sentiment_score as-of d (lookback window 5d)", ["research_synthesis"], 1),
    FeatureDef("research_confidence",      "research", "Most recent research_synthesis.confidence (0..1), lookback <=5d",
               "research_synthesis.confidence as-of d (lookback window 5d)", ["research_synthesis"], 1),
    FeatureDef("research_risk_flag_negative", "research", "1 if most recent research_synthesis has any risk_flags, else 0",
               "1 if len(risk_flags) > 0 as-of d (lookback window 5d) else 0", ["research_synthesis"], 1, output_type="bool"),

    # ── EVENT/CATALYST FEATURES (earnings_events, nse_corporate_filings, news_events) ─
    FeatureDef("catalyst_earnings_beat",   "events", "1 if EarningsEvent.beat_miss=='BEAT' within lookback window prior to d",
               "1 if any earnings_events.beat_miss=='BEAT' in [d-N, d] else 0", ["earnings_events"], 1, output_type="bool"),
    FeatureDef("catalyst_buyback",         "events", "1 if a buyback filing/news event occurred within lookback window prior to d",
               "1 if nse_corporate_filings.filing_type=='buyback' or news_events.event_type=='Buyback' in [d-N, d] else 0",
               ["nse_corporate_filings", "news_events"], 1, output_type="bool"),
    FeatureDef("catalyst_order_win",       "events", "1 if a large-order-win news event occurred within lookback window prior to d",
               "1 if news_events.event_type=='LargeOrder' in [d-N, d] else 0", ["news_events"], 1, output_type="bool"),
    FeatureDef("catalyst_dividend_hike",   "events", "1 if a dividend filing occurred within lookback window prior to d",
               "1 if nse_corporate_filings.filing_type=='dividend' or news_events.event_type=='Dividend' in [d-N, d] else 0",
               ["nse_corporate_filings", "news_events"], 1, output_type="bool"),
    FeatureDef("management_change_recent", "events", "1 if a management_change NewsEvent exists for the symbol within 10d prior to d",
               "1 if news_events.event_type=='ManagementChange' in [d-10, d] else 0", ["news_events"], 1, output_type="bool"),
    FeatureDef("days_to_earnings",         "events", "Calendar days to nearest upcoming EarningsEvent.earnings_date, null if none scheduled",
               "min(earnings_date - d) for earnings_date >= d", ["earnings_events"], 1, output_type="int"),
    FeatureDef("days_since_earnings",      "events", "Calendar days since nearest past EarningsEvent.earnings_date, null if none in lookback",
               "min(d - earnings_date) for earnings_date <= d, capped at 90d lookback", ["earnings_events"], 1, output_type="int"),

    # ── REGIME FEATURE (backend/markov module) ────────────────
    FeatureDef("regime_markov",            "market", "Current observable Markov regime label (BULL|BEAR|SIDEWAYS) as-of d",
               "markov_chain_daily.regime_state as-of d (most recent row <= d)", ["markov_chain_daily"], 1, output_type="str"),
]

# Fast lookup by name
CATALOG: dict[str, FeatureDef] = {f.name: f for f in FEATURE_CATALOG}


# ══════════════════════════════════════════════════════════════
# DB SEED
# ══════════════════════════════════════════════════════════════
def seed_feature_metadata(db: Session) -> int:
    """Insert / update FeatureMetadata rows for every catalog entry. Returns upserted count."""
    import json
    seen: set[str] = set()
    count = 0
    for feat in FEATURE_CATALOG:
        if feat.name in seen:
            log.warning("Duplicate feature name in catalog: %s — skipping", feat.name)
            continue
        seen.add(feat.name)
        existing = db.query(FeatureMetadata).filter_by(name=feat.name).first()
        if existing:
            existing.description = feat.description
            existing.formula     = feat.formula
            existing.inputs      = json.dumps(feat.inputs)
            existing.min_periods = feat.min_periods
            existing.version     = feat.version
            existing.category    = feat.category
            existing.output_type = feat.output_type
        else:
            db.add(FeatureMetadata(
                name        = feat.name,
                category    = feat.category,
                version     = feat.version,
                description = feat.description,
                formula     = feat.formula,
                inputs      = json.dumps(feat.inputs),
                output_type = feat.output_type,
                min_periods = feat.min_periods,
            ))
        count += 1
    db.commit()
    log.info("Feature metadata seeded — %d features.", count)
    return count

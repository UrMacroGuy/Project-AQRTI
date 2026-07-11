"""
AQRTI Database Models
SQLAlchemy ORM definitions — mirrors DATA_ARCHITECTURE.md schema exactly.
"""

from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, Index, JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ══════════════════════════════════════════════════════════════
# LAYER 1: STOCKS UNIVERSE
# ══════════════════════════════════════════════════════════════
class Stock(Base):
    __tablename__ = "stocks"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    symbol       = Column(String(20),  nullable=False, unique=True, index=True)
    name         = Column(String(120), nullable=False)
    sector       = Column(String(60),  nullable=True)
    industry     = Column(String(80),  nullable=True)
    market_cap   = Column(Float,       nullable=True)
    listing_date = Column(Date,        nullable=True)
    nifty_member = Column(Boolean,     default=False)
    active       = Column(Boolean,     default=True)

    prices       = relationship("DailyPrice",    back_populates="stock", lazy="dynamic")
    predictions  = relationship("Prediction",    back_populates="stock", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Stock {self.symbol}>"


# ══════════════════════════════════════════════════════════════
# LAYER 1: DAILY PRICES
# ══════════════════════════════════════════════════════════════
class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_price_symbol_date"),
        Index("ix_price_symbol", "symbol"),
        Index("ix_price_date",   "date"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    symbol          = Column(String(20), ForeignKey("stocks.symbol"), nullable=False)
    date            = Column(Date,       nullable=False)
    open            = Column(Float,      nullable=True)
    high            = Column(Float,      nullable=True)
    low             = Column(Float,      nullable=True)
    close           = Column(Float,      nullable=False)
    adj_close       = Column(Float,      nullable=True)
    volume          = Column(Float,      nullable=True)
    delivery_volume = Column(Float,      nullable=True)
    vwap            = Column(Float,      nullable=True)
    daily_return    = Column(Float,      nullable=True)

    stock = relationship("Stock", back_populates="prices")


# ══════════════════════════════════════════════════════════════
# LAYER 2: INDEX DATA
# ══════════════════════════════════════════════════════════════
class IndexData(Base):
    __tablename__ = "index_data"
    __table_args__ = (
        UniqueConstraint("index_name", "date", name="uq_index_date"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    index_name = Column(String(30),  nullable=False, index=True)
    date       = Column(Date,        nullable=False)
    open       = Column(Float,       nullable=True)
    high       = Column(Float,       nullable=True)
    low        = Column(Float,       nullable=True)
    close      = Column(Float,       nullable=False)
    volume     = Column(Float,       nullable=True)
    returns    = Column(Float,       nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER 3: CORPORATE EVENTS
# ══════════════════════════════════════════════════════════════
class CorporateEvent(Base):
    __tablename__ = "corporate_events"

    id                = Column(Integer,   primary_key=True, autoincrement=True)
    company           = Column(String(20), nullable=False, index=True)
    event_type        = Column(String(40), nullable=False)
    announcement_date = Column(Date,       nullable=True)
    event_date        = Column(Date,       nullable=True)
    details           = Column(Text,       nullable=True)
    impact_score      = Column(Float,      nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER 4: NEWS EVENTS
# ══════════════════════════════════════════════════════════════
class NewsEvent(Base):
    __tablename__ = "news_events"
    __table_args__ = (
        Index("ix_news_timestamp", "timestamp"),
        Index("ix_news_company",   "company"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    timestamp        = Column(DateTime,   nullable=False)
    headline         = Column(Text,       nullable=False)
    summary          = Column(Text,       nullable=True)
    source           = Column(String(80), nullable=True)
    company          = Column(String(20), nullable=True, index=True)
    sector           = Column(String(60), nullable=True)
    event_type       = Column(String(40), nullable=True)
    sentiment        = Column(String(12), nullable=True)   # positive/negative/neutral
    sentiment_score  = Column(Float,      nullable=True)   # -1.0 to 1.0
    impact_score     = Column(Float,      nullable=True)   # 0-100
    importance_score = Column(Float,      nullable=True)   # 0-100
    url              = Column(Text,       nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER 5: SENTIMENT RECORDS
# ══════════════════════════════════════════════════════════════
class SentimentRecord(Base):
    __tablename__ = "sentiment_records"
    __table_args__ = (
        Index("ix_sent_entity",    "entity"),
        Index("ix_sent_timestamp", "timestamp"),
    )

    id         = Column(Integer,    primary_key=True, autoincrement=True)
    timestamp  = Column(DateTime,   nullable=False)
    entity     = Column(String(40), nullable=False)  # symbol or sector name
    entity_type = Column(String(12), nullable=False)  # 'stock' | 'sector' | 'market'
    source     = Column(String(40), nullable=True)
    positive   = Column(Float,      nullable=True)
    negative   = Column(Float,      nullable=True)
    neutral    = Column(Float,      nullable=True)
    score      = Column(Float,      nullable=True)   # composite 0-100
    velocity   = Column(Float,      nullable=True)
    confidence = Column(Float,      nullable=True)
    virality   = Column(Float,      nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER 6: DERIVATIVES / OPTIONS DATA
# ══════════════════════════════════════════════════════════════
class OptionsData(Base):
    """DEPRECATED — superseded by OptionsChain (options_chain table). Zero active readers as of 2026-07-05. Do not write to this table; drop via migration after confirming zero readers via grep."""
    __tablename__ = "options_data"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_options_symbol_date"),
    )

    id             = Column(Integer,    primary_key=True, autoincrement=True)
    symbol         = Column(String(20), nullable=False, index=True)
    date           = Column(Date,       nullable=False)
    open_interest  = Column(Float,      nullable=True)
    oi_change      = Column(Float,      nullable=True)
    put_call_ratio = Column(Float,      nullable=True)
    max_pain       = Column(Float,      nullable=True)
    atm_iv         = Column(Float,      nullable=True)


# ══════════════════════════════════════════════════════════════
# PREDICTIONS
# ══════════════════════════════════════════════════════════════
class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_pred_date",   "date"),
        Index("ix_pred_symbol", "symbol"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    date            = Column(Date,       nullable=False)
    symbol          = Column(String(20), ForeignKey("stocks.symbol"), nullable=False)
    direction       = Column(String(12), nullable=True)   # Bullish/Bearish/Neutral
    confidence      = Column(Float,      nullable=True)   # 0-100
    expected_return = Column(Float,      nullable=True)   # percent
    risk_level      = Column(String(10), nullable=True)   # Low/Medium/High
    strategy        = Column(String(80), nullable=True)
    sentiment_score = Column(Float,      nullable=True)
    position_size   = Column(Float,      nullable=True)   # percent of portfolio
    actual_return   = Column(Float,      nullable=True)   # filled post-period
    success         = Column(Boolean,    nullable=True)   # filled post-period
    regime          = Column(String(30), nullable=True)
    model_version   = Column(String(40), nullable=True)
    reasoning       = Column(Text,       nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)

    stock = relationship("Stock", back_populates="predictions")


# ══════════════════════════════════════════════════════════════
# PAPER TRADES
# ══════════════════════════════════════════════════════════════
class Trade(Base):
    """DEPRECATED — superseded by PaperTrade (paper_trades table). The Risk page previously read this table and showed empty data because no rows exist. Do not write to this table; drop via migration after confirming zero readers via grep."""
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trade_symbol",     "symbol"),
        Index("ix_trade_entry_date", "entry_date"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    symbol           = Column(String(20), nullable=False)
    entry_date       = Column(Date,       nullable=False)
    exit_date        = Column(Date,       nullable=True)
    entry_price      = Column(Float,      nullable=False)
    exit_price       = Column(Float,      nullable=True)
    position_size    = Column(Float,      nullable=False)  # capital allocated
    position_pct     = Column(Float,      nullable=True)   # % of portfolio
    profit_loss      = Column(Float,      nullable=True)
    profit_loss_pct  = Column(Float,      nullable=True)
    strategy         = Column(String(80), nullable=True)
    confidence       = Column(Float,      nullable=True)
    predicted_return = Column(Float,      nullable=True)
    actual_return    = Column(Float,      nullable=True)
    exit_reason      = Column(String(40), nullable=True)
    is_open          = Column(Boolean,    default=True)
    prediction_id    = Column(Integer,    ForeignKey("predictions.id"), nullable=True)


# ══════════════════════════════════════════════════════════════
# FAILURES / MISTAKES
# ══════════════════════════════════════════════════════════════
class Mistake(Base):
    """DEPRECATED — v1 mistake/failure tracking, unused since the algo engine replaced the manual trading workflow. Do not write to this table; drop via migration after confirming zero readers via grep."""
    __tablename__ = "mistakes"
    __table_args__ = (
        Index("ix_mistake_symbol", "symbol"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    trade_id         = Column(Integer,    ForeignKey("trades.id"), nullable=True)
    prediction_id    = Column(Integer,    ForeignKey("predictions.id"), nullable=True)
    symbol           = Column(String(20), nullable=True)
    category         = Column(String(40), nullable=False)
    severity         = Column(String(10), nullable=True)   # low/medium/high/critical
    description      = Column(Text,       nullable=True)
    root_cause       = Column(Text,       nullable=True)
    lesson           = Column(Text,       nullable=True)
    pattern_detected = Column(Boolean,    default=False)
    resolved         = Column(Boolean,    default=False)
    created_at       = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# STRATEGIES
# ══════════════════════════════════════════════════════════════
class Strategy(Base):
    """DEPRECATED — v1 strategy table (strategies). Superseded by StrategyV2 (strategies_v2) which has full DSL, honest backtest gates, OOS, quarantine, and arena fields. Do not write to this table; drop via migration after confirming zero readers via grep."""
    __tablename__ = "strategies"

    id             = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id    = Column(String(30), nullable=False, unique=True, index=True)
    family         = Column(String(30), nullable=False)
    status         = Column(String(20), nullable=False, default="shadow")
    alpha_score    = Column(Float,      nullable=True)
    sharpe         = Column(Float,      nullable=True)
    sortino        = Column(Float,      nullable=True)
    win_rate       = Column(Float,      nullable=True)
    profit_factor  = Column(Float,      nullable=True)
    max_drawdown   = Column(Float,      nullable=True)
    regime         = Column(String(60), nullable=True)
    trade_count    = Column(Integer,    default=0)
    allowed_regimes = Column(String(120), nullable=True)
    entry_rules    = Column(Text,       nullable=True)
    exit_rules     = Column(Text,       nullable=True)
    created_at     = Column(DateTime,   default=datetime.utcnow)
    updated_at     = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# MODELS REGISTRY
# ══════════════════════════════════════════════════════════════
class ModelRecord(Base):
    """DEPRECATED — v1 model registry (model_registry). Superseded by MLModel and MLModelVersion tables which track CatBoost/NGBoost/AQRTINet artifacts and training metadata. Do not write to this table; drop via migration after confirming zero readers via grep."""
    __tablename__ = "model_registry"

    id                = Column(Integer,    primary_key=True, autoincrement=True)
    model_id          = Column(String(40), nullable=False, index=True)
    model_type        = Column(String(30), nullable=False)
    target            = Column(String(40), nullable=False)
    accuracy          = Column(Float,      nullable=True)
    calibration_ece   = Column(Float,      nullable=True)
    ensemble_weight   = Column(Float,      nullable=True)
    status            = Column(String(20), nullable=False, default="shadow")
    features_used     = Column(Integer,    nullable=True)
    feature_list      = Column(Text,       nullable=True)
    trained_at        = Column(DateTime,   nullable=True)
    promoted_at       = Column(DateTime,   nullable=True)
    is_active         = Column(Boolean,    default=False)


# ══════════════════════════════════════════════════════════════
# PORTFOLIO SNAPSHOTS
# ══════════════════════════════════════════════════════════════
class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    date           = Column(Date,    nullable=False, unique=True)
    total_value    = Column(Float,   nullable=False)
    cash           = Column(Float,   nullable=False)
    invested       = Column(Float,   nullable=False)
    daily_pnl      = Column(Float,   nullable=True)
    daily_pnl_pct  = Column(Float,   nullable=True)
    total_return   = Column(Float,   nullable=True)
    drawdown       = Column(Float,   nullable=True)
    sharpe_30d     = Column(Float,   nullable=True)
    open_positions = Column(Integer, nullable=True)


# ══════════════════════════════════════════════════════════════
# PHASE 2: FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════
class FeatureMetadata(Base):
    """Registry of all known features — one row per feature name."""
    __tablename__ = "feature_metadata"

    id          = Column(Integer,    primary_key=True, autoincrement=True)
    name        = Column(String(80), nullable=False, unique=True, index=True)
    category    = Column(String(30), nullable=False)   # price|volume|volatility|trend|market
    version     = Column(Integer,    nullable=False, default=1)
    description = Column(Text,       nullable=True)
    formula     = Column(Text,       nullable=True)    # human-readable derivation
    inputs      = Column(Text,       nullable=True)    # JSON list of raw columns used
    output_type = Column(String(20), nullable=True, default="float")  # float|bool|int
    min_periods = Column(Integer,    nullable=True)    # minimum rows required
    created_at  = Column(DateTime,   default=datetime.utcnow)
    updated_at  = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)


class FeatureValue(Base):
    """Computed feature values — one row per (symbol, date, feature_name, version)."""
    __tablename__ = "feature_values"
    __table_args__ = (
        UniqueConstraint("symbol", "date", "feature_name", "version",
                         name="uq_feature_symbol_date_name_ver"),
        Index("ix_fv_symbol_date",   "symbol", "date"),
        Index("ix_fv_feature_name",  "feature_name"),
    )

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    symbol       = Column(String(20), ForeignKey("stocks.symbol"), nullable=False)
    date         = Column(Date,       nullable=False)
    feature_name = Column(String(80), nullable=False)
    value        = Column(Float,      nullable=True)
    version      = Column(Integer,    nullable=False, default=1)
    computed_at  = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 2: NEWS — ENTITY MENTIONS (many-to-many news ↔ symbols)
# ══════════════════════════════════════════════════════════════
class EntityMention(Base):
    """Links a news event to a specific NSE symbol."""
    __tablename__ = "entity_mentions"
    __table_args__ = (
        Index("ix_em_news_id", "news_event_id"),
        Index("ix_em_symbol",  "symbol"),
    )

    id            = Column(Integer,    primary_key=True, autoincrement=True)
    news_event_id = Column(Integer,    ForeignKey("news_events.id"), nullable=False)
    symbol        = Column(String(20), nullable=False)
    sector        = Column(String(60), nullable=True)
    mention_type  = Column(String(20), nullable=True)   # primary|secondary
    created_at    = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 2: MARKET REGIMES
# ══════════════════════════════════════════════════════════════
class MarketRegime(Base):
    """Daily market regime classification with supporting signals."""
    __tablename__ = "market_regimes"
    __table_args__ = (
        UniqueConstraint("date", name="uq_regime_date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    date            = Column(Date,       nullable=False, index=True)
    regime          = Column(String(20), nullable=False)  # BULL|BEAR|SIDEWAYS|VOLATILE
    confidence      = Column(Float,      nullable=True)   # 0-100
    nifty_trend     = Column(String(10), nullable=True)   # UP|DOWN|FLAT
    breadth_pct     = Column(Float,      nullable=True)   # % stocks above EMA50
    volatility_pct  = Column(Float,      nullable=True)   # realized vol annualised
    sentiment_score = Column(Float,      nullable=True)   # market sentiment 0-100
    signal_summary  = Column(Text,       nullable=True)   # JSON dict of contributing signals
    created_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 3: ML PREDICTION LAYER
# ══════════════════════════════════════════════════════════════

class ModelVersion(Base):
    """Registry of trained model artifacts — one row per (model_name, task, label_col, version).

    label_col is part of the uniqueness key, not just task: direction_5d and
    outperform_binary both have task="direction", so (model_name, task,
    version) alone collided between them — see migration 0003 / BUG_HUNTING.md C13.
    """
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_name", "task", "label_col", "version", name="uq_mv_name_task_label_ver"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    model_name      = Column(String(20), nullable=False, index=True)   # lightgbm|xgboost|catboost
    task            = Column(String(30), nullable=False)               # direction|expected_return|outperformance
    label_col       = Column(String(40), nullable=False)               # direction_5d|expected_return|…
    version         = Column(Integer,    nullable=False, default=1)
    artifact_path   = Column(Text,       nullable=True)                # absolute path to .pkl file
    primary_metric  = Column(Float,      nullable=True)                # AUC / IC on test set
    metrics_json    = Column(Text,       nullable=True)                # JSON dict of all test metrics
    importance_json = Column(Text,       nullable=True)                # JSON dict top-20 features
    train_rows      = Column(Integer,    nullable=True)
    trained_at      = Column(DateTime,   nullable=True)
    is_active       = Column(Boolean,    default=False, index=True)


class ModelMetric(Base):
    """Per-fold metric storage from walk-forward validation."""
    __tablename__ = "model_metrics"
    __table_args__ = (
        Index("ix_mm_model_task_label", "model_name", "task", "label_col"),
        Index("ix_mm_computed_at",      "computed_at"),
    )

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    model_name   = Column(String(20), nullable=False)
    task         = Column(String(30), nullable=False)
    label_col    = Column(String(40), nullable=False, default="")
    version      = Column(Integer,    nullable=False, default=1)
    fold         = Column(Integer,    nullable=True)
    metric_name  = Column(String(40), nullable=False)    # accuracy|auc_roc|ic|mae|…
    metric_value = Column(Float,      nullable=False)
    split        = Column(String(10), nullable=False, default="test")  # train|val|test
    computed_at  = Column(DateTime,   nullable=False, default=datetime.utcnow)


class WalkForwardFold(Base):
    """Metadata for each walk-forward fold."""
    __tablename__ = "walk_forward_folds"
    __table_args__ = (
        UniqueConstraint("model_name", "task", "label_col", "version", "fold", name="uq_wff_model_task_label_ver_fold"),
    )

    id          = Column(Integer,    primary_key=True, autoincrement=True)
    model_name  = Column(String(20), nullable=False)
    task        = Column(String(30), nullable=False)
    label_col   = Column(String(40), nullable=False, default="")
    version     = Column(Integer,    nullable=False, default=1)
    fold        = Column(Integer,    nullable=False)
    train_start = Column(String(12), nullable=True)   # ISO date string
    train_end   = Column(String(12), nullable=True)
    test_start  = Column(String(12), nullable=True)
    test_end    = Column(String(12), nullable=True)
    train_rows  = Column(Integer,    nullable=True)
    test_rows   = Column(Integer,    nullable=True)
    status      = Column(String(20), nullable=False, default="pending")  # pending|complete|failed
    created_at  = Column(DateTime,   default=datetime.utcnow)


class PatternMatch(Base):
    """Stores pattern search results for each (symbol, date) query."""
    __tablename__ = "pattern_matches"
    __table_args__ = (
        UniqueConstraint("symbol", "search_date", name="uq_pm_symbol_date"),
        Index("ix_pm_symbol",      "symbol"),
        Index("ix_pm_search_date", "search_date"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    symbol              = Column(String(20), nullable=False)
    search_date         = Column(Date,       nullable=False)
    similar_situations  = Column(Text,       nullable=True)    # JSON list of top-5 matches
    expected_return     = Column(Float,      nullable=True)
    win_rate            = Column(Float,      nullable=True)
    outperform_rate     = Column(Float,      nullable=True)
    pattern_confidence  = Column(Float,      nullable=True)
    sample_size         = Column(Integer,    nullable=True)
    computed_at         = Column(DateTime,   default=datetime.utcnow)


class ConfidenceHistory(Base):
    """Stores confidence score components for each prediction."""
    __tablename__ = "confidence_history"
    __table_args__ = (
        UniqueConstraint("symbol", "prediction_date", name="uq_ch_symbol_date"),
        Index("ix_ch_symbol",          "symbol"),
        Index("ix_ch_prediction_date", "prediction_date"),
    )

    id                    = Column(Integer,    primary_key=True, autoincrement=True)
    symbol                = Column(String(20), nullable=False)
    prediction_date       = Column(Date,       nullable=False)
    confidence_score      = Column(Float,      nullable=True)
    confidence_category   = Column(String(20), nullable=True)  # Exceptional|Strong|Good|Weak|Ignore
    model_agreement       = Column(Float,      nullable=True)
    historical_accuracy   = Column(Float,      nullable=True)
    regime_confidence     = Column(Float,      nullable=True)
    signal_strength       = Column(Float,      nullable=True)
    feature_completeness  = Column(Float,      nullable=True)
    component_scores_json = Column(Text,       nullable=True)  # JSON
    computed_at           = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 4: PAPER TRADING LAYER
# ══════════════════════════════════════════════════════════════

class PaperPortfolio(Base):
    """Master portfolio state — one active row per (portfolio_name, version)."""
    __tablename__ = "paper_portfolios"
    __table_args__ = (
        UniqueConstraint("portfolio_name", name="uq_pp_name"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    portfolio_name   = Column(String(40), nullable=False, default="default")
    initial_capital  = Column(Float,      nullable=False)
    current_cash     = Column(Float,      nullable=False)
    total_value      = Column(Float,      nullable=False)
    total_return_pct = Column(Float,      nullable=True, default=0.0)
    max_drawdown_pct = Column(Float,      nullable=True, default=0.0)
    peak_value       = Column(Float,      nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)
    updated_at       = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)


class PaperPosition(Base):
    """One row per open position. Closed positions are removed from this table."""
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("portfolio_name", "symbol", name="uq_pos_portfolio_symbol"),
        Index("ix_pos_symbol", "symbol"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    portfolio_name   = Column(String(40), nullable=False, default="default")
    symbol           = Column(String(20), nullable=False)
    sector           = Column(String(60), nullable=True)
    entry_date       = Column(Date,       nullable=False)
    entry_price      = Column(Float,      nullable=False)
    shares           = Column(Float,      nullable=False)        # can be fractional
    capital_deployed = Column(Float,      nullable=False)        # entry_price * shares
    weight_pct       = Column(Float,      nullable=True)         # % of portfolio at entry
    direction        = Column(String(12), nullable=True)         # Bullish|Bearish
    confidence       = Column(Float,      nullable=True)
    expected_return  = Column(Float,      nullable=True)
    stop_loss_price  = Column(Float,      nullable=True)
    target_price     = Column(Float,      nullable=True)
    prediction_id    = Column(Integer,    ForeignKey("predictions.id"), nullable=True)
    strategy_id      = Column(String(80), nullable=True)
    strategy_name    = Column(String(120),nullable=True)
    opened_at        = Column(DateTime,   default=datetime.utcnow)


class PaperTrade(Base):
    """Complete record of every simulated trade (entry + exit)."""
    __tablename__ = "paper_trades"
    __table_args__ = (
        Index("ix_pt_symbol",     "symbol"),
        Index("ix_pt_entry_date", "entry_date"),
        Index("ix_pt_exit_date",  "exit_date"),
        CheckConstraint("shares >= 0", name="ck_pt_shares_nonneg"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    portfolio_name   = Column(String(40), nullable=False, default="default")
    symbol           = Column(String(20), nullable=False)
    sector           = Column(String(60), nullable=True)
    entry_date       = Column(Date,       nullable=False)
    exit_date        = Column(Date,       nullable=True)
    entry_price      = Column(Float,      nullable=False)
    exit_price       = Column(Float,      nullable=True)
    shares           = Column(Float,      nullable=False)
    capital_deployed = Column(Float,      nullable=False)
    weight_pct       = Column(Float,      nullable=True)
    gross_pnl        = Column(Float,      nullable=True)         # capital * return
    gross_pnl_pct    = Column(Float,      nullable=True)
    direction        = Column(String(12), nullable=True)
    confidence       = Column(Float,      nullable=True)
    predicted_return = Column(Float,      nullable=True)
    actual_return    = Column(Float,      nullable=True)
    exit_reason      = Column(String(40), nullable=True)         # rebalance|stop_loss|target|held
    is_open          = Column(Boolean,    default=True)
    holding_days     = Column(Integer,    nullable=True)
    prediction_id    = Column(Integer,    ForeignKey("predictions.id"), nullable=True)
    strategy_id      = Column(String(80), nullable=True)
    strategy_name    = Column(String(120),nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)


class EquityCurvePoint(Base):
    """Daily equity curve — one row per (portfolio_name, date)."""
    __tablename__ = "equity_curve"
    __table_args__ = (
        UniqueConstraint("portfolio_name", "date", name="uq_ec_portfolio_date"),
        Index("ix_ec_date", "date"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    portfolio_name   = Column(String(40), nullable=False, default="default")
    date             = Column(Date,       nullable=False)
    total_value      = Column(Float,      nullable=False)
    cash             = Column(Float,      nullable=False)
    invested         = Column(Float,      nullable=False)
    daily_return_pct = Column(Float,      nullable=True)
    cumulative_return_pct = Column(Float, nullable=True)
    drawdown_pct     = Column(Float,      nullable=True)
    open_positions   = Column(Integer,    nullable=True, default=0)
    nifty_close      = Column(Float,      nullable=True)         # benchmark for alpha calc
    recorded_at      = Column(DateTime,   default=datetime.utcnow)


class PerformanceSnapshot(Base):
    """Rolling performance analytics — one row per (portfolio_name, date)."""
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        UniqueConstraint("portfolio_name", "date", name="uq_perf_portfolio_date"),
        Index("ix_perf_date", "date"),
    )

    id                   = Column(Integer,    primary_key=True, autoincrement=True)
    portfolio_name       = Column(String(40), nullable=False, default="default")
    date                 = Column(Date,       nullable=False)
    # Returns
    total_return_pct     = Column(Float,      nullable=True)
    cagr_pct             = Column(Float,      nullable=True)
    daily_return_avg     = Column(Float,      nullable=True)
    # Risk
    sharpe_ratio         = Column(Float,      nullable=True)
    sortino_ratio        = Column(Float,      nullable=True)
    max_drawdown_pct     = Column(Float,      nullable=True)
    current_drawdown_pct = Column(Float,      nullable=True)
    volatility_ann       = Column(Float,      nullable=True)
    # Trade stats
    total_trades         = Column(Integer,    nullable=True, default=0)
    open_trades          = Column(Integer,    nullable=True, default=0)
    closed_trades        = Column(Integer,    nullable=True, default=0)
    winning_trades       = Column(Integer,    nullable=True, default=0)
    losing_trades        = Column(Integer,    nullable=True, default=0)
    win_rate_pct         = Column(Float,      nullable=True)
    profit_factor        = Column(Float,      nullable=True)
    expectancy_pct       = Column(Float,      nullable=True)
    avg_win_pct          = Column(Float,      nullable=True)
    avg_loss_pct         = Column(Float,      nullable=True)
    avg_holding_days     = Column(Float,      nullable=True)
    # Exposure
    avg_exposure_pct     = Column(Float,      nullable=True)
    turnover_pct         = Column(Float,      nullable=True)    # capital rotated / avg portfolio
    computed_at          = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 5: LEARNING ENGINE + KNOWLEDGE SYSTEM
# ══════════════════════════════════════════════════════════════

class KnowledgeEvent(Base):
    """Atomic unit of institutional memory — every notable event AQRTI observes."""
    __tablename__ = "knowledge_events"
    __table_args__ = (
        Index("ix_ke_date",        "event_date"),
        Index("ix_ke_category",    "category"),
        Index("ix_ke_symbol",      "symbol"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    event_date      = Column(Date,       nullable=False)
    category        = Column(String(40), nullable=False)  # prediction|trade|failure|success|regime|pattern
    symbol          = Column(String(20), nullable=True)
    event_type      = Column(String(60), nullable=True)   # e.g. "bullish_correct", "overconfidence_failure"
    description     = Column(Text,       nullable=True)
    outcome         = Column(String(20), nullable=True)   # positive|negative|neutral
    magnitude       = Column(Float,      nullable=True)   # scale of impact: 0–100
    confidence_at   = Column(Float,      nullable=True)   # AQRTI confidence when event occurred
    actual_result   = Column(Float,      nullable=True)   # actual return / outcome metric
    regime          = Column(String(20), nullable=True)
    metadata_json   = Column(Text,       nullable=True)   # additional structured context
    created_at      = Column(DateTime,   default=datetime.utcnow)


class FailureRecord(Base):
    """Detailed record of every prediction or trade failure."""
    __tablename__ = "failure_records"
    __table_args__ = (
        Index("ix_fr_date",     "failure_date"),
        Index("ix_fr_symbol",   "symbol"),
        Index("ix_fr_category", "failure_category"),
    )

    id                = Column(Integer,    primary_key=True, autoincrement=True)
    failure_date      = Column(Date,       nullable=False)
    symbol            = Column(String(20), nullable=True)
    failure_category  = Column(String(40), nullable=False)  # false_positive|false_negative|overconfidence|regime|sentiment|feature|pattern|portfolio
    failure_type      = Column(String(60), nullable=True)   # specific type within category
    severity          = Column(String(10), nullable=True)   # low|medium|high|critical
    predicted_value   = Column(Float,      nullable=True)
    actual_value      = Column(Float,      nullable=True)
    confidence_at     = Column(Float,      nullable=True)
    regime_at         = Column(String(20), nullable=True)
    root_cause        = Column(Text,       nullable=True)   # auto-generated explanation
    contributing_factors = Column(Text,   nullable=True)   # JSON list
    lesson            = Column(Text,       nullable=True)   # extracted actionable lesson
    prediction_id     = Column(Integer,    ForeignKey("predictions.id"), nullable=True)
    trade_id          = Column(Integer,    ForeignKey("paper_trades.id"), nullable=True)
    resolved          = Column(Boolean,    default=False)
    created_at        = Column(DateTime,   default=datetime.utcnow)


class ModelDriftHistory(Base):
    """Tracks model performance drift over time."""
    __tablename__ = "model_drift_history"
    __table_args__ = (
        Index("ix_mdh_model",  "model_name"),
        Index("ix_mdh_date",   "measured_date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    model_name      = Column(String(20), nullable=False)
    task            = Column(String(30), nullable=False)
    version         = Column(Integer,    nullable=False, default=1)
    measured_date   = Column(Date,       nullable=False)
    window_days     = Column(Integer,    nullable=True, default=30)
    accuracy        = Column(Float,      nullable=True)
    auc_roc         = Column(Float,      nullable=True)
    ic              = Column(Float,      nullable=True)
    calibration_ece = Column(Float,      nullable=True)   # expected calibration error
    directional_acc = Column(Float,      nullable=True)
    baseline_metric = Column(Float,      nullable=True)   # metric at training time
    drift_pct       = Column(Float,      nullable=True)   # (current - baseline) / baseline * 100
    drift_flag      = Column(Boolean,    default=False)   # True if drift exceeds threshold
    sample_size     = Column(Integer,    nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class ModelWeight(Base):
    """Stores ensemble weights per model per task, updated by weight_optimizer."""
    __tablename__ = "model_weights"
    __table_args__ = (
        UniqueConstraint("model_name", "task", name="uq_mw_model_task"),
    )

    id          = Column(Integer,    primary_key=True, autoincrement=True)
    model_name  = Column(String(20), nullable=False)
    task        = Column(String(30), nullable=False)
    weight      = Column(Float,      nullable=False, default=0.25)
    updated_at  = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)


class FeatureImportanceHistory(Base):
    """Daily snapshot of feature importance scores from all active models."""
    __tablename__ = "feature_importance_history"
    __table_args__ = (
        UniqueConstraint("feature_name", "model_name", "task", "measured_date",
                         name="uq_fih_feat_model_date"),
        Index("ix_fih_feature",  "feature_name"),
        Index("ix_fih_date",     "measured_date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    feature_name    = Column(String(80), nullable=False)
    model_name      = Column(String(20), nullable=False)
    task            = Column(String(30), nullable=False)
    version         = Column(Integer,    nullable=False, default=1)
    measured_date   = Column(Date,       nullable=False)
    importance      = Column(Float,      nullable=True)   # raw importance score
    rank            = Column(Integer,    nullable=True)   # rank among all features
    ic              = Column(Float,      nullable=True)   # information coefficient
    created_at      = Column(DateTime,   default=datetime.utcnow)


class FeatureDecayHistory(Base):
    """Tracks feature predictive power decay over rolling windows."""
    __tablename__ = "feature_decay_history"
    __table_args__ = (
        Index("ix_fdh_feature", "feature_name"),
        Index("ix_fdh_date",    "measured_date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    feature_name    = Column(String(80), nullable=False)
    measured_date   = Column(Date,       nullable=False)
    ic_30d          = Column(Float,      nullable=True)
    ic_90d          = Column(Float,      nullable=True)
    ic_180d         = Column(Float,      nullable=True)
    ic_trend        = Column(Float,      nullable=True)   # slope of IC over time
    decay_flag      = Column(Boolean,    default=False)   # True if significant decay detected
    decay_severity  = Column(String(10), nullable=True)   # none|mild|moderate|severe
    created_at      = Column(DateTime,   default=datetime.utcnow)


class PatternOutcome(Base):
    """Stores actual outcomes for previously matched historical patterns."""
    __tablename__ = "pattern_outcomes"
    __table_args__ = (
        UniqueConstraint("symbol", "prediction_date", name="uq_po_symbol_date"),
        Index("ix_po_symbol", "symbol"),
        Index("ix_po_date",   "prediction_date"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    symbol              = Column(String(20), nullable=False)
    prediction_date     = Column(Date,       nullable=False)
    pattern_confidence  = Column(Float,      nullable=True)
    predicted_return    = Column(Float,      nullable=True)
    actual_return_5d    = Column(Float,      nullable=True)
    actual_return_10d   = Column(Float,      nullable=True)
    was_correct         = Column(Boolean,    nullable=True)   # direction correct?
    outperformed_nifty  = Column(Boolean,    nullable=True)
    top_similar_symbol  = Column(String(20), nullable=True)
    similarity_score    = Column(Float,      nullable=True)
    regime_at           = Column(String(20), nullable=True)
    evaluated_at        = Column(DateTime,   default=datetime.utcnow)


class KnowledgeScore(Base):
    """Daily AQRTI intelligence score — 0-100 composite."""
    __tablename__ = "knowledge_scores"
    __table_args__ = (
        UniqueConstraint("date", name="uq_ks_date"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    date                = Column(Date,       nullable=False)
    overall_score       = Column(Float,      nullable=False)   # 0-100 composite
    prediction_quality  = Column(Float,      nullable=True)    # accuracy-derived
    portfolio_quality   = Column(Float,      nullable=True)    # sharpe/win-rate derived
    risk_quality        = Column(Float,      nullable=True)    # drawdown/VaR adherence
    learning_quality    = Column(Float,      nullable=True)    # failure resolution rate
    calibration_quality = Column(Float,      nullable=True)    # confidence accuracy
    feature_quality     = Column(Float,      nullable=True)    # feature health
    score_delta         = Column(Float,      nullable=True)    # change from prior day
    events_processed    = Column(Integer,    nullable=True)
    failures_detected   = Column(Integer,    nullable=True)
    lessons_generated   = Column(Integer,    nullable=True)
    created_at          = Column(DateTime,   default=datetime.utcnow)


class LessonLearned(Base):
    """Actionable lessons extracted from failure analysis and pattern evaluation."""
    __tablename__ = "lessons_learned"
    __table_args__ = (
        Index("ix_ll_date",     "lesson_date"),
        Index("ix_ll_category", "category"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    lesson_date     = Column(Date,       nullable=False)
    category        = Column(String(40), nullable=False)  # prediction|portfolio|risk|model|feature|pattern
    title           = Column(String(200), nullable=False)
    description     = Column(Text,       nullable=True)
    what_happened   = Column(Text,       nullable=True)
    why_it_happened = Column(Text,       nullable=True)
    what_worked     = Column(Text,       nullable=True)
    what_failed     = Column(Text,       nullable=True)
    recommendation  = Column(Text,       nullable=True)
    severity        = Column(String(10), nullable=True)   # info|warning|critical
    symbol          = Column(String(20), nullable=True)
    regime          = Column(String(20), nullable=True)
    source_failure_id = Column(Integer,  ForeignKey("failure_records.id"), nullable=True)
    applied         = Column(Boolean,    default=False)
    created_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 6: STRATEGY DISCOVERY & EVOLUTION SYSTEM
# ══════════════════════════════════════════════════════════════

class StrategyV2(Base):
    """
    Full strategy record — replaces the minimal Strategy table.
    Stores the complete DSL definition, lifecycle state, and all
    backtest/live metrics in one place.
    """
    __tablename__ = "strategies_v2"
    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_sv2_id"),
        Index("ix_sv2_status",   "status"),
        Index("ix_sv2_family",   "family"),
        Index("ix_sv2_fitness",  "fitness_score"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id      = Column(String(40), nullable=False, unique=True)   # AQRTI_STR_<hash>
    name             = Column(String(120), nullable=True)
    family           = Column(String(40), nullable=False)   # momentum|mean_reversion|breakout|sentiment|regime|hybrid
    # Separate namespace from `family` — same isolation pattern as
    # arena_status below. "stock" strategies trade the existing
    # DailyPrice/get_backtest_universe pipeline; "index_futures" strategies
    # trade IndexFuturesPrice and must never be mixed into stock arena
    # rounds, stock benchmark comparisons, or stock promotion pools.
    asset_class      = Column(String(20), nullable=False, default="stock")
    # Which index this strategy trades — only set when asset_class ==
    # "index_futures" (NIFTY50|BANKNIFTY|SENSEX|NIFTYIT|NIFTYPHARMA). A
    # stock strategy trades a multi-symbol universe (no single value fits);
    # an index-futures strategy trades exactly one instrument, so this is
    # a plain column rather than forcing it into the DSL's universe concept.
    index_name       = Column(String(30), nullable=True)
    generation       = Column(Integer,    nullable=False, default=0)   # 0=seed, 1=evolved, etc.
    parent_ids       = Column(Text,       nullable=True)    # JSON list of parent strategy_ids
    # DSL definition
    dsl_json         = Column(Text,       nullable=False)   # serialised StrategyDSL object
    feature_categories = Column(Text,    nullable=True)    # JSON list of category names used
    allowed_regimes  = Column(Text,       nullable=True)    # JSON list e.g. ["BULL","SIDEWAYS"]
    # Lifecycle
    status           = Column(String(20), nullable=False, default="candidate")
    # candidate → shadow → promoted → active → retired → archived
    # Owned exclusively by strategy_lifecycle.py's promote_strategy/retire_strategy.
    # The arena (arena/arena_engine.py) must NEVER write "champion"/"needs_review"
    # here — see arena_status below. A prior version of the arena did write into
    # this field, silently colliding with the lifecycle state machine and
    # (via auto_promote_strategies) bypassing the human-approval + paper-trading
    # quarantine gate required before "active". Fixed 2026-07-03.
    status_reason    = Column(Text,       nullable=True)
    promoted_at      = Column(DateTime,   nullable=True)
    retired_at       = Column(DateTime,   nullable=True)
    # Arena refinement state — separate namespace from `status` above so the
    # arena's internal grading (champion / refining / needs_review) can never
    # collide with or bypass the human-approval lifecycle state machine.
    arena_status     = Column(String(20), nullable=True)   # None|refining|champion|needs_review
    arena_rounds     = Column(Integer,    nullable=True, default=0)
    # Fitness / Backtest Metrics
    fitness_score    = Column(Float,      nullable=True)    # 0-100 composite
    sharpe           = Column(Float,      nullable=True)
    sortino          = Column(Float,      nullable=True)
    win_rate         = Column(Float,      nullable=True)    # percent
    profit_factor    = Column(Float,      nullable=True)
    max_drawdown     = Column(Float,      nullable=True)    # percent (negative)
    expectancy       = Column(Float,      nullable=True)    # average gain per trade
    trade_count      = Column(Integer,    nullable=True, default=0)
    avg_holding_days = Column(Float,      nullable=True)
    exposure_pct     = Column(Float,      nullable=True)    # avg % capital deployed
    # Regime performance
    bull_sharpe      = Column(Float,      nullable=True)
    bear_sharpe      = Column(Float,      nullable=True)
    sideways_sharpe  = Column(Float,      nullable=True)
    volatile_sharpe  = Column(Float,      nullable=True)
    # Out-of-sample (walk-forward holdout) results
    oos_sharpe       = Column(Float,      nullable=True)
    oos_win_rate     = Column(Float,      nullable=True)
    oos_trades       = Column(Integer,    nullable=True)
    oos_passed       = Column(Boolean,    nullable=True)
    # Meta
    backtest_start   = Column(Date,       nullable=True)
    backtest_end     = Column(Date,       nullable=True)
    backtest_universe = Column(Integer,   nullable=True)    # number of stocks tested
    created_at       = Column(DateTime,   default=datetime.utcnow)
    updated_at       = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)


class StrategyVersion(Base):
    """Immutable snapshot of a strategy DSL at each evolution step."""
    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version", name="uq_strver_id_ver"),
        Index("ix_strver_id",   "strategy_id"),
    )

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id  = Column(String(40), ForeignKey("strategies_v2.strategy_id"), nullable=False)
    version      = Column(Integer,    nullable=False, default=1)
    dsl_json     = Column(Text,       nullable=False)
    fitness_score = Column(Float,     nullable=True)
    change_type  = Column(String(30), nullable=True)   # mutation|crossover|seed|manual
    change_desc  = Column(Text,       nullable=True)
    created_at   = Column(DateTime,   default=datetime.utcnow)


class StrategyPerformance(Base):
    """Daily live (paper) performance record per strategy."""
    __tablename__ = "strategy_performance"
    __table_args__ = (
        UniqueConstraint("strategy_id", "date", name="uq_sp_id_date"),
        Index("ix_sp_date", "date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id     = Column(String(40), ForeignKey("strategies_v2.strategy_id"), nullable=False)
    date            = Column(Date,       nullable=False)
    signals_fired   = Column(Integer,    nullable=True, default=0)
    trades_opened   = Column(Integer,    nullable=True, default=0)
    trades_closed   = Column(Integer,    nullable=True, default=0)
    daily_pnl       = Column(Float,      nullable=True)
    daily_pnl_pct   = Column(Float,      nullable=True)
    cumulative_pnl  = Column(Float,      nullable=True)
    win_count       = Column(Integer,    nullable=True, default=0)
    loss_count      = Column(Integer,    nullable=True, default=0)
    regime_at       = Column(String(20), nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class StrategyEvolutionHistory(Base):
    """Audit log for every evolution operation (mutation/crossover/retirement)."""
    __tablename__ = "strategy_evolution_history"
    __table_args__ = (
        Index("ix_seh_child",  "child_strategy_id"),
        Index("ix_seh_date",   "evolved_date"),
    )

    id                 = Column(Integer,    primary_key=True, autoincrement=True)
    child_strategy_id  = Column(String(40), nullable=False)
    parent_strategy_ids = Column(Text,     nullable=True)   # JSON list
    evolved_date       = Column(Date,       nullable=False)
    operation          = Column(String(30), nullable=False)  # mutation|crossover|seed|retire
    operation_detail   = Column(Text,       nullable=True)   # JSON describing what changed
    parent_fitness     = Column(Float,      nullable=True)
    child_fitness      = Column(Float,      nullable=True)
    fitness_delta      = Column(Float,      nullable=True)
    regime_at          = Column(String(20), nullable=True)
    created_at         = Column(DateTime,   default=datetime.utcnow)


class StrategyGraveyard(Base):
    """
    Permanent record of every retired/failed strategy.
    Strategies are NEVER deleted — they inform future generation.
    """
    __tablename__ = "strategy_graveyard"
    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_sg_id"),
        Index("ix_sg_family",        "family"),
        Index("ix_sg_failure_reason", "failure_reason"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id      = Column(String(40), nullable=False)
    name             = Column(String(120), nullable=True)
    family           = Column(String(40), nullable=True)
    generation       = Column(Integer,    nullable=True)
    dsl_json         = Column(Text,       nullable=True)
    final_fitness    = Column(Float,      nullable=True)
    final_sharpe     = Column(Float,      nullable=True)
    final_win_rate   = Column(Float,      nullable=True)
    failure_reason   = Column(String(80), nullable=True)   # low_fitness|regime_break|drawdown|decay|manual
    failure_detail   = Column(Text,       nullable=True)
    regime_at_death  = Column(String(20), nullable=True)
    lessons_json     = Column(Text,       nullable=True)   # JSON list of lessons extracted
    lifespan_days    = Column(Integer,    nullable=True)
    trade_count      = Column(Integer,    nullable=True)
    buried_at        = Column(DateTime,   default=datetime.utcnow)


class StrategyBacktestTrade(Base):
    """Individual trade records from strategy backtests — powers per-strategy trade log and replay."""
    __tablename__ = "strategy_backtest_trades"
    __table_args__ = (
        Index("ix_sbt_strategy_id", "strategy_id"),
        Index("ix_sbt_symbol",      "symbol"),
        Index("ix_sbt_entry_date",  "entry_date"),
    )

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id  = Column(String(40), nullable=False)
    symbol       = Column(String(20), nullable=False)
    entry_date   = Column(Date,       nullable=False)
    exit_date    = Column(Date,       nullable=True)
    entry_price  = Column(Float,      nullable=False)
    exit_price   = Column(Float,      nullable=True)
    pnl_pct      = Column(Float,      nullable=True)
    exit_reason  = Column(String(40), nullable=True)
    holding_days = Column(Integer,    nullable=True)
    created_at   = Column(DateTime,   default=datetime.utcnow)


class StrategyResearchReport(Base):
    """Auto-generated research reports from the meta research engine."""
    __tablename__ = "strategy_research_reports"
    __table_args__ = (
        Index("ix_srr_date",     "report_date"),
        Index("ix_srr_category", "category"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    report_date     = Column(Date,       nullable=False)
    category        = Column(String(40), nullable=False)   # feature_analysis|regime_analysis|family_survival|evolution_summary
    title           = Column(String(200), nullable=False)
    summary         = Column(Text,       nullable=True)
    findings_json   = Column(Text,       nullable=True)    # structured JSON findings
    recommendations = Column(Text,       nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 7: MULTI-AGENT RESEARCH SYSTEM
# ══════════════════════════════════════════════════════════════

class Agent(Base):
    """Registry of all AQRTI research agents and their current state."""
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_id"),
        Index("ix_agent_type", "agent_type"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    agent_id        = Column(String(40), nullable=False, unique=True)   # e.g. "market_research"
    name            = Column(String(80), nullable=False)
    agent_type      = Column(String(40), nullable=False)                # market|news|strategy|model|risk|pattern|cro
    description     = Column(Text,       nullable=True)
    status          = Column(String(20), nullable=False, default="idle") # idle|running|error|disabled
    last_run_at     = Column(DateTime,   nullable=True)
    last_run_status = Column(String(20), nullable=True)                  # success|error|skipped
    last_run_summary = Column(Text,      nullable=True)
    run_count       = Column(Integer,    nullable=False, default=0)
    error_count     = Column(Integer,    nullable=False, default=0)
    config_json     = Column(Text,       nullable=True)                  # agent-specific config
    created_at      = Column(DateTime,   default=datetime.utcnow)
    updated_at      = Column(DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentTask(Base):
    """Task assigned to an agent — by the CRO or the scheduler."""
    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("ix_at_agent",   "agent_id"),
        Index("ix_at_status",  "status"),
        Index("ix_at_date",    "created_at"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    task_id         = Column(String(40), nullable=False, unique=True)
    agent_id        = Column(String(40), ForeignKey("agents.agent_id"), nullable=False)
    assigned_by     = Column(String(40), nullable=True)                  # "scheduler"|"cro"|"manual"
    task_type       = Column(String(60), nullable=False)                 # "daily_run"|"deep_analysis"|"follow_up"
    title           = Column(String(200), nullable=False)
    description     = Column(Text,       nullable=True)
    priority        = Column(Integer,    nullable=False, default=5)      # 1=critical, 10=low
    status          = Column(String(20), nullable=False, default="pending") # pending|running|completed|failed|cancelled
    input_json      = Column(Text,       nullable=True)                  # task parameters
    output_json     = Column(Text,       nullable=True)                  # task result
    error_message   = Column(Text,       nullable=True)
    started_at      = Column(DateTime,   nullable=True)
    completed_at    = Column(DateTime,   nullable=True)
    due_date        = Column(Date,       nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class AgentReport(Base):
    """Research report produced by an agent from a single run."""
    __tablename__ = "agent_reports"
    __table_args__ = (
        Index("ix_ar_agent",    "agent_id"),
        Index("ix_ar_date",     "report_date"),
        Index("ix_ar_category", "category"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    agent_id        = Column(String(40), ForeignKey("agents.agent_id"), nullable=False)
    task_id         = Column(String(40), ForeignKey("agent_tasks.task_id"), nullable=True)
    report_date     = Column(Date,       nullable=False)
    category        = Column(String(40), nullable=False)    # market|news|strategy|model|risk|pattern|brief
    title           = Column(String(200), nullable=False)
    summary         = Column(Text,       nullable=True)
    findings_json   = Column(Text,       nullable=True)     # structured findings dict
    recommendations_json = Column(Text,  nullable=True)     # list of recommended actions
    urgency         = Column(String(10), nullable=False, default="normal") # low|normal|high|critical
    read            = Column(Boolean,    nullable=False, default=False)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class AgentMessage(Base):
    """Inter-agent messages — agent-to-agent communication log."""
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("ix_am_from",  "from_agent"),
        Index("ix_am_to",    "to_agent"),
        Index("ix_am_date",  "created_at"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    from_agent      = Column(String(40), nullable=False)
    to_agent        = Column(String(40), nullable=False)
    message_type    = Column(String(40), nullable=False)    # "finding"|"alert"|"request"|"response"|"broadcast"
    subject         = Column(String(200), nullable=True)
    body            = Column(Text,       nullable=True)
    payload_json    = Column(Text,       nullable=True)     # structured data
    priority        = Column(Integer,    nullable=False, default=5)
    read            = Column(Boolean,    nullable=False, default=False)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class ResearchBrief(Base):
    """Daily Intelligence Brief generated by the CRO agent."""
    __tablename__ = "research_briefs"
    __table_args__ = (
        UniqueConstraint("brief_date", name="uq_rb_date"),
        Index("ix_rb_date", "brief_date"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    brief_date          = Column(Date,       nullable=False)
    title               = Column(String(200), nullable=False)
    market_summary      = Column(Text,       nullable=True)
    top_opportunities   = Column(Text,       nullable=True)   # JSON list
    major_risks         = Column(Text,       nullable=True)   # JSON list
    model_insights      = Column(Text,       nullable=True)   # JSON list
    strategy_insights   = Column(Text,       nullable=True)   # JSON list
    research_findings   = Column(Text,       nullable=True)   # JSON list
    lessons_learned     = Column(Text,       nullable=True)   # JSON list
    action_items        = Column(Text,       nullable=True)   # JSON list — for human review
    regime_at           = Column(String(20), nullable=True)
    knowledge_score     = Column(Float,      nullable=True)
    agent_reports_used  = Column(Text,       nullable=True)   # JSON list of report IDs
    created_at          = Column(DateTime,   default=datetime.utcnow)


class ResearchFinding(Base):
    """Individual finding extracted from agent analysis — normalized, searchable."""
    __tablename__ = "research_findings"
    __table_args__ = (
        Index("ix_rf_date",     "finding_date"),
        Index("ix_rf_agent",    "agent_id"),
        Index("ix_rf_category", "category"),
        Index("ix_rf_symbol",   "symbol"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    finding_date    = Column(Date,       nullable=False)
    agent_id        = Column(String(40), nullable=False)
    category        = Column(String(40), nullable=False)   # market|news|strategy|model|risk|pattern
    subcategory     = Column(String(40), nullable=True)
    title           = Column(String(200), nullable=False)
    description     = Column(Text,       nullable=True)
    evidence        = Column(Text,       nullable=True)    # supporting data points
    implication     = Column(Text,       nullable=True)    # what this means for AQRTI
    urgency         = Column(String(10), nullable=False, default="normal")
    symbol          = Column(String(20), nullable=True)    # if finding is stock-specific
    regime          = Column(String(20), nullable=True)
    metadata_json   = Column(Text,       nullable=True)
    actioned        = Column(Boolean,    nullable=False, default=False)
    created_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 8.5: HISTORICAL INTELLIGENCE TRAINING SYSTEM
# ══════════════════════════════════════════════════════════════

class HistoricalReplay(Base):
    """Log of every historical replay run — metadata only, no raw data stored."""
    __tablename__ = "historical_replays"
    __table_args__ = (
        Index("ix_hr_type",  "replay_type"),
        Index("ix_hr_date",  "created_at"),
    )

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    replay_type  = Column(String(20), nullable=False)       # day|week|month|regime|event|horizon_datasets
    scope_label  = Column(String(80), nullable=True)        # e.g. "2024-03-15" or "BULL"
    symbols_count = Column(Integer,   nullable=True)
    snapshots_count = Column(Integer, nullable=True)
    samples_count = Column(Integer,   nullable=True)
    metadata_json = Column(Text,      nullable=True)
    created_at   = Column(DateTime,   default=datetime.utcnow)


class RegimeDataset(Base):
    """Metadata for each regime-specific training dataset."""
    __tablename__ = "regime_datasets"
    __table_args__ = (
        UniqueConstraint("regime_label", name="uq_rd_label"),
        Index("ix_rd_label", "regime_label"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    regime_label     = Column(String(40), nullable=False)
    definition_json  = Column(Text,       nullable=True)
    dates_json       = Column(Text,       nullable=True)    # JSON list of ISO date strings
    sample_count     = Column(Integer,    nullable=True, default=0)
    symbols_json     = Column(Text,       nullable=True)    # JSON list of symbols
    date_range_start = Column(Date,       nullable=True)
    date_range_end   = Column(Date,       nullable=True)
    metadata_json    = Column(Text,       nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)


class MetaLearningRecord(Base):
    """Insight generated by the meta-learning engine about AQRTI's own predictions."""
    __tablename__ = "meta_learning_records"
    __table_args__ = (
        Index("ix_mlr_type", "insight_type"),
        Index("ix_mlr_date", "created_at"),
    )

    id             = Column(Integer,    primary_key=True, autoincrement=True)
    insight_type   = Column(String(40), nullable=False)     # overconfidence|failure|trust|regime
    title          = Column(String(200), nullable=False)
    description    = Column(Text,       nullable=True)
    condition_text = Column(Text,       nullable=True)
    evidence_json  = Column(Text,       nullable=True)
    failure_rate   = Column(Float,      nullable=True)
    sample_count   = Column(Integer,    nullable=True)
    severity       = Column(String(10), nullable=True)      # low|medium|high|critical
    created_at     = Column(DateTime,   default=datetime.utcnow)


class FeatureProposal(Base):
    """A proposed new feature generated by the feature discovery engine."""
    __tablename__ = "feature_proposals"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_fp_id"),
        Index("ix_fp_status", "status"),
        Index("ix_fp_name",   "feature_name"),
    )

    id                   = Column(Integer,    primary_key=True, autoincrement=True)
    proposal_id          = Column(String(40), nullable=False)
    feature_name         = Column(String(80), nullable=False)
    category             = Column(String(30), nullable=True)
    description          = Column(Text,       nullable=True)
    formula              = Column(Text,       nullable=True)
    rationale            = Column(Text,       nullable=True)
    expected_impact      = Column(Text,       nullable=True)
    source_failures_json = Column(Text,       nullable=True)
    estimated_ic         = Column(Float,      nullable=True)
    status               = Column(String(20), nullable=False, default="proposed")
    rejection_reason     = Column(Text,       nullable=True)
    approved_at          = Column(DateTime,   nullable=True)
    created_at           = Column(DateTime,   default=datetime.utcnow)


class FeatureValidation(Base):
    """Backtest results for a proposed feature."""
    __tablename__ = "feature_validations"
    __table_args__ = (
        Index("ix_fv2_proposal", "proposal_id"),
        Index("ix_fv2_date",     "validation_date"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    proposal_id      = Column(String(40), nullable=False)
    ic_overall       = Column(Float,      nullable=True)
    ic_by_regime_json = Column(Text,      nullable=True)
    horizon_days     = Column(Integer,    nullable=True)
    sample_count     = Column(Integer,    nullable=True)
    validation_date  = Column(Date,       nullable=True)
    status           = Column(String(20), nullable=True)    # useful|weak|invalid
    created_at       = Column(DateTime,   default=datetime.utcnow)


class ModelMemory(Base):
    """Reliability scoring and historical performance record for each ML model."""
    __tablename__ = "model_memory"
    __table_args__ = (
        Index("ix_mm2_model",  "model_name"),
        Index("ix_mm2_date",   "computed_at"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    model_name          = Column(String(30), nullable=False)
    task                = Column(String(30), nullable=False)
    overall_reliability = Column(Float,      nullable=True)    # 0-100
    regime_scores_json  = Column(Text,       nullable=True)    # JSON {regime: score}
    recent_accuracy     = Column(Float,      nullable=True)
    drift_score         = Column(Float,      nullable=True)    # 0=stable, 100=drifted
    failure_count       = Column(Integer,    nullable=True, default=0)
    success_count       = Column(Integer,    nullable=True, default=0)
    recommendation      = Column(String(20), nullable=True)    # trust|caution|retrain|retire
    computed_at         = Column(DateTime,   default=datetime.utcnow)


class StrategyMemory(Base):
    """Permanent record of every strategy's lifecycle and lessons."""
    __tablename__ = "strategy_memory"
    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_sm_id"),
        Index("ix_sm_family", "family"),
        Index("ix_sm_status", "status"),
    )

    id                 = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id        = Column(String(40), nullable=False)
    name               = Column(String(120), nullable=True)
    family             = Column(String(40), nullable=True)
    status             = Column(String(20), nullable=True)
    survival_days      = Column(Integer,    nullable=True, default=0)
    final_fitness      = Column(Float,      nullable=True)
    peak_fitness       = Column(Float,      nullable=True)
    decay_detected     = Column(Boolean,    default=False)
    failure_reason     = Column(String(80), nullable=True)
    best_regimes_json  = Column(Text,       nullable=True)
    worst_regimes_json = Column(Text,       nullable=True)
    lessons_json       = Column(Text,       nullable=True)
    computed_at        = Column(DateTime,   default=datetime.utcnow)


class ResearchMemory(Base):
    """Daily research memory snapshot — synthesized from all research sources."""
    __tablename__ = "research_memory"
    __table_args__ = (
        UniqueConstraint("memory_date", name="uq_rm_date"),
        Index("ix_rm_date", "memory_date"),
    )

    id            = Column(Integer,    primary_key=True, autoincrement=True)
    memory_date   = Column(Date,       nullable=False)
    summary_json  = Column(Text,       nullable=True)
    themes_json   = Column(Text,       nullable=True)
    total_records = Column(Integer,    nullable=True, default=0)
    created_at    = Column(DateTime,   default=datetime.utcnow)


class FailurePattern(Base):
    """Recurring failure patterns identified by the meta-learning engine."""
    __tablename__ = "failure_patterns"
    __table_args__ = (
        Index("ix_fatp_type",  "pattern_type"),
        Index("ix_fatp_date",  "first_seen"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    pattern_type    = Column(String(40), nullable=False)
    description     = Column(Text,       nullable=True)
    condition       = Column(Text,       nullable=True)
    occurrence_count = Column(Integer,   nullable=True, default=1)
    failure_rate    = Column(Float,      nullable=True)
    regimes_json    = Column(Text,       nullable=True)    # JSON list of regimes where seen
    first_seen      = Column(Date,       nullable=True)
    last_seen       = Column(Date,       nullable=True)
    resolved        = Column(Boolean,    default=False)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class PredictionPattern(Base):
    """Recurring success patterns — conditions that reliably produce correct predictions."""
    __tablename__ = "prediction_patterns"
    __table_args__ = (
        Index("ix_pp2_type", "pattern_type"),
        Index("ix_pp2_date", "first_seen"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    pattern_type    = Column(String(40), nullable=False)
    description     = Column(Text,       nullable=True)
    condition       = Column(Text,       nullable=True)
    occurrence_count = Column(Integer,   nullable=True, default=1)
    success_rate    = Column(Float,      nullable=True)
    regimes_json    = Column(Text,       nullable=True)
    first_seen      = Column(Date,       nullable=True)
    last_seen       = Column(Date,       nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 7.5: HISTORICAL INTELLIGENCE VAULT
# ══════════════════════════════════════════════════════════════

class MarketSnapshot(Base):
    """Immutable daily snapshot of all market state — prices, regime, features, sentiment."""
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_market_snapshot_date"),
        Index("ix_ms_date",   "snapshot_date"),
        Index("ix_ms_regime", "regime"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    snapshot_date   = Column(Date,       nullable=False)
    regime          = Column(String(20), nullable=True)
    regime_conf     = Column(Float,      nullable=True)
    nifty_close     = Column(Float,      nullable=True)
    nifty_return_1d = Column(Float,      nullable=True)
    nifty_return_5d = Column(Float,      nullable=True)
    nifty_volatility= Column(Float,      nullable=True)
    market_sentiment= Column(Float,      nullable=True)   # avg sentiment score
    advance_decline = Column(Float,      nullable=True)   # ratio
    stocks_json     = Column(Text,       nullable=True)   # JSON: [{symbol, close, ret_1d, …}]
    features_json   = Column(Text,       nullable=True)   # JSON: market-level feature vector
    news_summary    = Column(Text,       nullable=True)   # JSON: {count, top_topics, avg_sentiment}
    knowledge_score = Column(Float,      nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class PredictionArchive(Base):
    """Immutable archive of every prediction made — never overwritten."""
    __tablename__ = "prediction_archive"
    __table_args__ = (
        Index("ix_pa_date",   "prediction_date"),
        Index("ix_pa_symbol", "symbol"),
        Index("ix_pa_model",  "model_name"),
    )

    id                = Column(Integer,    primary_key=True, autoincrement=True)
    prediction_date   = Column(Date,       nullable=False)
    symbol            = Column(String(20), nullable=False)
    model_name        = Column(String(60), nullable=True)
    direction         = Column(String(10), nullable=True)   # BUY/SELL/HOLD
    direction_conf    = Column(Float,      nullable=True)
    magnitude_pct     = Column(Float,      nullable=True)
    horizon_days      = Column(Integer,    nullable=True)
    features_used     = Column(Text,       nullable=True)   # JSON list
    regime_at         = Column(String(20), nullable=True)
    actual_direction  = Column(String(10), nullable=True)   # filled on outcome
    actual_return     = Column(Float,      nullable=True)   # filled on outcome
    outcome_date      = Column(Date,       nullable=True)
    was_correct       = Column(Boolean,    nullable=True)
    archive_run_id    = Column(String(40), nullable=True)   # batch identifier
    created_at        = Column(DateTime,   default=datetime.utcnow)


class PortfolioArchive(Base):
    """Daily snapshot of paper portfolio state — permanent record."""
    __tablename__ = "portfolio_archive"
    __table_args__ = (
        UniqueConstraint("archive_date", name="uq_portfolio_archive_date"),
        Index("ix_por_date", "archive_date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    archive_date    = Column(Date,       nullable=False)
    total_value     = Column(Float,      nullable=True)
    cash            = Column(Float,      nullable=True)
    invested        = Column(Float,      nullable=True)
    total_pnl       = Column(Float,      nullable=True)
    total_return_pct= Column(Float,      nullable=True)
    sharpe          = Column(Float,      nullable=True)
    max_drawdown    = Column(Float,      nullable=True)
    win_rate        = Column(Float,      nullable=True)
    positions_json  = Column(Text,       nullable=True)   # JSON: [{symbol, qty, value, …}]
    trades_json     = Column(Text,       nullable=True)   # JSON: trades opened/closed today
    regime_at       = Column(String(20), nullable=True)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class StrategyArchive(Base):
    """Immutable record of every strategy that ever existed — even deleted/buried ones."""
    __tablename__ = "strategy_archive"
    __table_args__ = (
        Index("ix_sa_strategy_id", "strategy_id"),
        Index("ix_sa_date",        "archive_date"),
        Index("ix_sa_status",      "status_at_archive"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id      = Column(String(64), nullable=False)
    archive_date     = Column(Date,       nullable=False)
    name             = Column(String(120), nullable=True)
    family           = Column(String(40), nullable=True)
    generation       = Column(Integer,    nullable=True)
    fitness_score    = Column(Float,      nullable=True)
    status_at_archive= Column(String(20), nullable=True)
    parent_ids       = Column(Text,       nullable=True)   # JSON list
    dsl_json         = Column(Text,       nullable=True)   # full DSL snapshot
    backtest_json    = Column(Text,       nullable=True)   # backtest summary
    regime_fit_json  = Column(Text,       nullable=True)   # per-regime performance
    lifecycle_note   = Column(Text,       nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)


class KnowledgeArchive(Base):
    """Daily knowledge state snapshot — lessons, failures, score history."""
    __tablename__ = "knowledge_archive"
    __table_args__ = (
        UniqueConstraint("archive_date", name="uq_knowledge_archive_date"),
        Index("ix_ka_date", "archive_date"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    archive_date     = Column(Date,       nullable=False)
    knowledge_score  = Column(Float,      nullable=True)
    lessons_count    = Column(Integer,    nullable=True)
    failures_count   = Column(Integer,    nullable=True)
    lessons_json     = Column(Text,       nullable=True)   # JSON: top lessons of the day
    drift_summary    = Column(Text,       nullable=True)   # JSON: drift flags per model
    feature_rankings = Column(Text,       nullable=True)   # JSON: top 20 features
    model_accuracy   = Column(Text,       nullable=True)   # JSON: {model: accuracy}
    regime_at        = Column(String(20), nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)


class ResearchArchive(Base):
    """Permanent archive of all research outputs — briefs, findings, agent reports."""
    __tablename__ = "research_archive"
    __table_args__ = (
        Index("ix_ra_date",     "archive_date"),
        Index("ix_ra_type",     "archive_type"),
        Index("ix_ra_agent_id", "agent_id"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    archive_date    = Column(Date,       nullable=False)
    archive_type    = Column(String(30), nullable=False)   # brief|finding|agent_report|strategy_report
    agent_id        = Column(String(40), nullable=True)
    title           = Column(String(200), nullable=True)
    summary         = Column(Text,       nullable=True)
    full_content    = Column(Text,       nullable=True)    # JSON or Markdown
    urgency         = Column(String(10), nullable=True)
    regime_at       = Column(String(20), nullable=True)
    source_id       = Column(Integer,    nullable=True)    # FK to original record (loose)
    created_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 8: DATA SUPREMACY LAYER
# ══════════════════════════════════════════════════════════════

class NSECorporateFiling(Base):
    """NSE corporate filings — results, announcements, board meetings, dividends, splits."""
    __tablename__ = "nse_corporate_filings"
    __table_args__ = (
        UniqueConstraint("symbol", "filing_date", "filing_type", "source_id", name="uq_nse_filing"),
        Index("ix_ncf_symbol",      "symbol"),
        Index("ix_ncf_date",        "filing_date"),
        Index("ix_ncf_type",        "filing_type"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    symbol          = Column(String(20), nullable=False)
    company_name    = Column(String(120),nullable=True)
    filing_date     = Column(Date,       nullable=False)
    filing_type     = Column(String(40), nullable=False)  # results|dividend|split|buyback|merger|board_meeting|announcement
    subject         = Column(Text,       nullable=True)
    details         = Column(Text,       nullable=True)   # JSON: structured extracted fields
    attachment_url  = Column(Text,       nullable=True)
    source_id       = Column(String(80), nullable=True)   # NSE internal ID for dedup
    impact_score    = Column(Float,      nullable=True)   # computed 0-100
    sentiment_score = Column(Float,      nullable=True)   # -1 to 1
    scraped_at      = Column(DateTime,   default=datetime.utcnow)
    created_at      = Column(DateTime,   default=datetime.utcnow)


class FIIDIIFlow(Base):
    """Daily FII/DII buy/sell data — equity + derivatives."""
    __tablename__ = "fii_dii_flows"
    __table_args__ = (
        UniqueConstraint("flow_date", "category", name="uq_fii_dii_date_cat"),
        Index("ix_fdf_date",     "flow_date"),
        Index("ix_fdf_category", "category"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    flow_date       = Column(Date,       nullable=False)
    category        = Column(String(10), nullable=False)  # FII|DII
    gross_buy       = Column(Float,      nullable=True)   # crores
    gross_sell      = Column(Float,      nullable=True)   # crores
    net_investment  = Column(Float,      nullable=True)   # crores (buy - sell)
    segment         = Column(String(20), nullable=True)   # equity|debt|hybrid|total
    # Derived
    net_5d          = Column(Float,      nullable=True)   # rolling 5-day net
    net_20d         = Column(Float,      nullable=True)   # rolling 20-day net
    flow_signal     = Column(String(10), nullable=True)   # BULLISH|BEARISH|NEUTRAL
    scraped_at      = Column(DateTime,   default=datetime.utcnow)


class OptionsChain(Base):
    """Daily NSE options chain snapshot — PCR, max pain, OI concentration."""
    __tablename__ = "options_chain"
    __table_args__ = (
        UniqueConstraint("symbol", "expiry_date", "snapshot_date", name="uq_options_chain"),
        Index("ix_oc_symbol",   "symbol"),
        Index("ix_oc_snapshot", "snapshot_date"),
        Index("ix_oc_expiry",   "expiry_date"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    symbol          = Column(String(20), nullable=False)
    snapshot_date   = Column(Date,       nullable=False)
    expiry_date     = Column(Date,       nullable=True)
    spot_price      = Column(Float,      nullable=True)
    pcr_oi          = Column(Float,      nullable=True)   # put-call ratio (OI based)
    pcr_volume      = Column(Float,      nullable=True)   # put-call ratio (volume based)
    max_pain        = Column(Float,      nullable=True)   # max pain strike
    atm_strike      = Column(Float,      nullable=True)
    atm_iv          = Column(Float,      nullable=True)   # implied volatility at ATM
    iv_skew         = Column(Float,      nullable=True)   # OTM put IV - OTM call IV
    total_call_oi   = Column(Float,      nullable=True)
    total_put_oi    = Column(Float,      nullable=True)
    highest_call_oi_strike = Column(Float, nullable=True)
    highest_put_oi_strike  = Column(Float, nullable=True)
    chain_json      = Column(Text,       nullable=True)   # full chain as JSON (top 10 strikes each side)
    scraped_at      = Column(DateTime,   default=datetime.utcnow)


class MarketBreadth(Base):
    """Daily market breadth metrics — advance/decline, 52W highs/lows, sector breadth."""
    __tablename__ = "market_breadth"
    __table_args__ = (
        UniqueConstraint("breadth_date", "universe", name="uq_mb_date_universe"),
        Index("ix_mb_date",     "breadth_date"),
        Index("ix_mb_universe", "universe"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    breadth_date        = Column(Date,       nullable=False)
    universe            = Column(String(20), nullable=False, default="NIFTY500")  # NIFTY50|NIFTY500|ALL
    total_stocks        = Column(Integer,    nullable=True)
    advancing           = Column(Integer,    nullable=True)
    declining           = Column(Integer,    nullable=True)
    unchanged           = Column(Integer,    nullable=True)
    advance_decline_ratio = Column(Float,    nullable=True)
    new_52w_high        = Column(Integer,    nullable=True)
    new_52w_low         = Column(Integer,    nullable=True)
    above_ma20          = Column(Integer,    nullable=True)  # count above 20DMA
    above_ma50          = Column(Integer,    nullable=True)  # count above 50DMA
    above_ma200         = Column(Integer,    nullable=True)  # count above 200DMA
    breadth_thrust      = Column(Float,      nullable=True)  # Zweig breadth thrust
    mcclellan_osc       = Column(Float,      nullable=True)  # McClellan oscillator
    sector_breadth_json = Column(Text,       nullable=True)  # JSON: {sector: {adv, dec, ratio}}
    breadth_signal      = Column(String(10), nullable=True)  # STRONG_BULL|BULL|NEUTRAL|BEAR|STRONG_BEAR
    scraped_at          = Column(DateTime,   default=datetime.utcnow)


class SectorRotation(Base):
    """Daily sector relative strength and rotation metrics."""
    __tablename__ = "sector_rotation"
    __table_args__ = (
        UniqueConstraint("rotation_date", "sector", name="uq_sr_date_sector"),
        Index("ix_sr_date",   "rotation_date"),
        Index("ix_sr_sector", "sector"),
        Index("ix_sr_phase",  "rotation_phase"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    rotation_date   = Column(Date,       nullable=False)
    sector          = Column(String(40), nullable=False)
    ret_1d          = Column(Float,      nullable=True)
    ret_5d          = Column(Float,      nullable=True)
    ret_20d         = Column(Float,      nullable=True)
    ret_60d         = Column(Float,      nullable=True)
    rs_vs_nifty_20d = Column(Float,      nullable=True)  # relative strength vs Nifty50
    rs_vs_nifty_60d = Column(Float,      nullable=True)
    rs_rank         = Column(Integer,    nullable=True)  # rank 1=strongest
    avg_volume_ratio= Column(Float,      nullable=True)  # sector volume vs 20d avg
    avg_sentiment   = Column(Float,      nullable=True)  # avg sentiment score in sector
    rotation_phase  = Column(String(20), nullable=True)  # LEADING|WEAKENING|LAGGING|IMPROVING (RRG quadrant)
    momentum_score  = Column(Float,      nullable=True)
    top_stocks_json = Column(Text,       nullable=True)  # JSON: [{symbol, ret_20d, rs_rank}]
    scraped_at      = Column(DateTime,   default=datetime.utcnow)


class EarningsEvent(Base):
    """Scheduled and actual earnings events — estimates vs actuals."""
    __tablename__ = "earnings_events"
    __table_args__ = (
        UniqueConstraint("symbol", "earnings_date", "period", name="uq_earn_symbol_date_period"),
        Index("ix_ee_symbol",  "symbol"),
        Index("ix_ee_date",    "earnings_date"),
        Index("ix_ee_quarter", "quarter"),
    )

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    symbol              = Column(String(20), nullable=False)
    company_name        = Column(String(120),nullable=True)
    earnings_date       = Column(Date,       nullable=False)
    period              = Column(String(10), nullable=True)   # Q1|Q2|Q3|Q4|FY
    quarter             = Column(String(10), nullable=True)   # e.g. Q1FY26
    # Actuals (post-result)
    revenue_actual      = Column(Float,      nullable=True)   # crores
    pat_actual          = Column(Float,      nullable=True)   # profit after tax, crores
    ebitda_actual       = Column(Float,      nullable=True)
    eps_actual          = Column(Float,      nullable=True)
    # YoY/QoQ
    revenue_yoy_pct     = Column(Float,      nullable=True)
    pat_yoy_pct         = Column(Float,      nullable=True)
    eps_yoy_pct         = Column(Float,      nullable=True)
    revenue_qoq_pct     = Column(Float,      nullable=True)
    pat_qoq_pct         = Column(Float,      nullable=True)
    # Beat/Miss
    beat_miss           = Column(String(10), nullable=True)   # BEAT|MISS|IN_LINE
    surprise_pct        = Column(Float,      nullable=True)   # vs estimate
    # Market reaction
    price_reaction_1d   = Column(Float,      nullable=True)   # % change next day
    price_reaction_5d   = Column(Float,      nullable=True)
    # Metadata
    result_status       = Column(String(10), nullable=False, default="scheduled")  # scheduled|declared
    scraped_at          = Column(DateTime,   default=datetime.utcnow)
    created_at          = Column(DateTime,   default=datetime.utcnow)


class DataSourceHealth(Base):
    """Health monitoring for every external data source."""
    __tablename__ = "data_source_health"
    __table_args__ = (
        UniqueConstraint("check_date", "source_name", name="uq_dsh_date_source"),
        Index("ix_dsh_date",   "check_date"),
        Index("ix_dsh_source", "source_name"),
        Index("ix_dsh_status", "status"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    check_date      = Column(Date,       nullable=False)
    source_name     = Column(String(60), nullable=False)  # nse_corporate|fii_dii|options|breadth|sector|earnings
    status          = Column(String(10), nullable=False, default="unknown")  # ok|degraded|down|unknown
    records_fetched = Column(Integer,    nullable=True)
    fetch_duration_ms = Column(Integer,  nullable=True)
    error_message   = Column(Text,       nullable=True)
    last_success_at = Column(DateTime,   nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    schema_valid    = Column(Boolean,    nullable=True)
    notes           = Column(Text,       nullable=True)
    scraped_at      = Column(DateTime,   default=datetime.utcnow)


class DataQualityLog(Base):
    """Per-dataset data quality checks — completeness, freshness, schema validity."""
    __tablename__ = "data_quality_log"
    __table_args__ = (
        Index("ix_dql_date",    "check_date"),
        Index("ix_dql_dataset", "dataset_name"),
    )

    id              = Column(Integer,    primary_key=True, autoincrement=True)
    check_date      = Column(Date,       nullable=False)
    dataset_name    = Column(String(60), nullable=False)
    total_records   = Column(Integer,    nullable=True)
    null_pct        = Column(Float,      nullable=True)      # % null in key columns
    duplicate_pct   = Column(Float,      nullable=True)
    freshness_hours = Column(Float,      nullable=True)      # hours since last update
    schema_errors   = Column(Integer,    nullable=True)
    quality_score   = Column(Float,      nullable=True)      # 0-100 composite
    quality_grade   = Column(String(2),  nullable=True)      # A|B|C|D|F
    issues_json     = Column(Text,       nullable=True)      # JSON list of detected issues
    scraped_at      = Column(DateTime,   default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 15: AUTOMATIC REGIME DISCOVERY
# ══════════════════════════════════════════════════════════════

class DiscoveredRegime(Base):
    __tablename__ = "discovered_regimes"
    __table_args__ = (UniqueConstraint("regime_id", name="uq_discovered_regime_id"),)

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    regime_id              = Column(String(20), nullable=False, unique=True, index=True)
    label                  = Column(String(80), nullable=True)
    description            = Column(Text, nullable=True)
    cluster_center_json    = Column(Text, nullable=True)
    feature_names_json     = Column(Text, nullable=True)
    avg_volatility         = Column(Float, nullable=True)
    avg_breadth            = Column(Float, nullable=True)
    avg_momentum           = Column(Float, nullable=True)
    avg_volume_ratio       = Column(Float, nullable=True)
    momentum_failure_rate  = Column(Float, nullable=True)
    typical_duration_days  = Column(Float, nullable=True)
    sample_count           = Column(Integer, default=0)
    first_seen             = Column(Date, nullable=True)
    last_seen              = Column(Date, nullable=True)
    is_active              = Column(Boolean, default=True)
    created_at             = Column(DateTime, default=datetime.utcnow)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DailyRegimeAssignment(Base):
    __tablename__ = "daily_regime_assignments"
    __table_args__ = (UniqueConstraint("date", name="uq_regime_date"),)

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    date                   = Column(Date, nullable=False, unique=True, index=True)
    regime_id              = Column(String(20), nullable=False, index=True)
    confidence             = Column(Float, nullable=True)
    transition_probability = Column(Float, nullable=True)
    feature_vector_json    = Column(Text, nullable=True)
    nearest_centroid_dist  = Column(Float, nullable=True)
    created_at             = Column(DateTime, default=datetime.utcnow)


class RegimeTransitionMatrix(Base):
    __tablename__ = "regime_transition_matrix"
    __table_args__ = (UniqueConstraint("from_regime", "to_regime", name="uq_regime_transition"),)

    id                        = Column(Integer, primary_key=True, autoincrement=True)
    from_regime               = Column(String(20), nullable=False, index=True)
    to_regime                 = Column(String(20), nullable=False)
    transition_count          = Column(Integer, default=0)
    transition_probability    = Column(Float, default=0.0)
    avg_duration_before_days  = Column(Float, nullable=True)
    updated_at                = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 16: COUNTERFACTUAL LEARNING
# ══════════════════════════════════════════════════════════════

class CounterfactualSimulation(Base):
    __tablename__ = "counterfactual_simulations"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    source_type          = Column(String(20), nullable=False)
    source_id            = Column(Integer, nullable=False, index=True)
    symbol               = Column(String(20), nullable=False, index=True)
    original_date        = Column(Date, nullable=False)
    scenario_type        = Column(String(60), nullable=False)
    scenario_params_json = Column(Text, nullable=True)
    original_return      = Column(Float, nullable=True)
    simulated_return     = Column(Float, nullable=True)
    return_delta         = Column(Float, nullable=True)
    original_regime      = Column(String(30), nullable=True)
    lesson_generated     = Column(Text, nullable=True)
    confidence           = Column(Float, nullable=True)
    created_at           = Column(DateTime, default=datetime.utcnow)


class CounterfactualLesson(Base):
    __tablename__ = "counterfactual_lessons"

    id                       = Column(Integer, primary_key=True, autoincrement=True)
    lesson_date              = Column(Date, nullable=False, index=True)
    scenario_type            = Column(String(60), nullable=False, index=True)
    regime                   = Column(String(30), nullable=True)
    title                    = Column(String(200), nullable=False)
    description              = Column(Text, nullable=False)
    avg_return_delta         = Column(Float, nullable=True)
    sample_count             = Column(Integer, default=0)
    confidence               = Column(Float, nullable=True)
    applies_to_families_json = Column(Text, nullable=True)
    applied_count            = Column(Integer, default=0)
    created_at               = Column(DateTime, default=datetime.utcnow)
    updated_at               = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 17: STRATEGY DNA & GENEALOGY
# ══════════════════════════════════════════════════════════════

class StrategyDNA(Base):
    __tablename__ = "strategy_dna"
    __table_args__ = (UniqueConstraint("strategy_id", name="uq_dna_strategy"),)

    id                       = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id              = Column(String(40), nullable=False, unique=True, index=True)
    family                   = Column(String(40), nullable=True)
    dominant_features_json   = Column(Text, nullable=True)
    indicator_set_json       = Column(Text, nullable=True)
    avg_holding_days         = Column(Float, nullable=True)
    avg_volatility_at_entry  = Column(Float, nullable=True)
    avg_drawdown             = Column(Float, nullable=True)
    preferred_regime         = Column(String(30), nullable=True)
    worst_regime             = Column(String(30), nullable=True)
    avg_confidence           = Column(Float, nullable=True)
    sector_preference_json   = Column(Text, nullable=True)
    generation               = Column(Integer, default=0)
    mutation_history_json    = Column(Text, nullable=True)
    parent_ids_json          = Column(Text, nullable=True)
    child_ids_json           = Column(Text, nullable=True)
    dna_hash                 = Column(String(64), nullable=True, index=True)
    similarity_scores_json   = Column(Text, nullable=True)
    created_at               = Column(DateTime, default=datetime.utcnow)
    updated_at               = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 18: FEATURE DISCOVERY
# ══════════════════════════════════════════════════════════════

class FeatureCandidate(Base):
    __tablename__ = "feature_candidates"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id          = Column(String(40), nullable=False, unique=True, index=True)
    name                  = Column(String(100), nullable=False)
    formula               = Column(Text, nullable=False)
    category              = Column(String(40), nullable=True)
    source                = Column(String(40), nullable=True)
    parent_features_json  = Column(Text, nullable=True)
    hypothesis            = Column(Text, nullable=True)
    ic_score              = Column(Float, nullable=True)
    ic_by_regime_json     = Column(Text, nullable=True)
    validation_status     = Column(String(20), default="pending")
    validation_details_json = Column(Text, nullable=True)
    rejection_reason      = Column(Text, nullable=True)
    backtest_sharpe       = Column(Float, nullable=True)
    sample_count          = Column(Integer, default=0)
    created_at            = Column(DateTime, default=datetime.utcnow)
    validated_at          = Column(DateTime, nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER 19: KNOWLEDGE GRAPH
# ══════════════════════════════════════════════════════════════

class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (UniqueConstraint("node_type", "node_key", name="uq_node"),)

    id              = Column(Integer, primary_key=True, autoincrement=True)
    node_type       = Column(String(30), nullable=False, index=True)
    node_key        = Column(String(100), nullable=False, index=True)
    label           = Column(String(200), nullable=True)
    properties_json = Column(Text, nullable=True)
    confidence      = Column(Float, default=1.0)
    evidence_count  = Column(Integer, default=0)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (UniqueConstraint("from_node_id", "to_node_id", "edge_type", name="uq_edge"),)

    id            = Column(Integer, primary_key=True, autoincrement=True)
    from_node_id  = Column(Integer, ForeignKey("knowledge_nodes.id"), nullable=False, index=True)
    to_node_id    = Column(Integer, ForeignKey("knowledge_nodes.id"), nullable=False, index=True)
    edge_type     = Column(String(40), nullable=False, index=True)
    weight        = Column(Float, default=1.0)
    confidence    = Column(Float, default=1.0)
    evidence_json = Column(Text, nullable=True)
    evidence_count = Column(Integer, default=1)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 20: HYPOTHESIS & EXPERIMENT ENGINE
# ══════════════════════════════════════════════════════════════

class ResearchHypothesis(Base):
    __tablename__ = "research_hypotheses"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    hypothesis_id         = Column(String(40), nullable=False, unique=True, index=True)
    title                 = Column(String(300), nullable=False)
    description           = Column(Text, nullable=False)
    category              = Column(String(60), nullable=True)
    priority              = Column(Float, default=50.0)
    status                = Column(String(20), default="pending")
    generated_by          = Column(String(40), nullable=True)
    evidence_for_json     = Column(Text, nullable=True)
    evidence_against_json = Column(Text, nullable=True)
    experiment_design_json = Column(Text, nullable=True)
    result_summary        = Column(Text, nullable=True)
    significance_score    = Column(Float, nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)
    resolved_at           = Column(DateTime, nullable=True)


class ResearchExperiment(Base):
    __tablename__ = "research_experiments"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id  = Column(String(40), nullable=False, unique=True, index=True)
    hypothesis_id  = Column(String(40), nullable=False, index=True)
    name           = Column(String(200), nullable=False)
    design_json    = Column(Text, nullable=True)
    status         = Column(String(20), default="scheduled")
    result_json    = Column(Text, nullable=True)
    p_value        = Column(Float, nullable=True)
    effect_size    = Column(Float, nullable=True)
    sample_size    = Column(Integer, nullable=True)
    conclusion     = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    completed_at   = Column(DateTime, nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER 21: CHAMPION-CHALLENGER FRAMEWORK
# ══════════════════════════════════════════════════════════════

class ModelArena(Base):
    __tablename__ = "model_arena"
    __table_args__ = (UniqueConstraint("model_name", "version", name="uq_arena_model"),)

    id                = Column(Integer, primary_key=True, autoincrement=True)
    model_name        = Column(String(60), nullable=False, index=True)
    version           = Column(Integer, nullable=False)
    role              = Column(String(20), default="challenger")
    artifact_path     = Column(String(300), nullable=True)
    accuracy          = Column(Float, nullable=True)
    precision_score   = Column(Float, nullable=True)
    recall_score      = Column(Float, nullable=True)
    auc               = Column(Float, nullable=True)
    calibration_ece   = Column(Float, nullable=True)
    paper_win_rate    = Column(Float, nullable=True)
    paper_sharpe      = Column(Float, nullable=True)
    paper_drawdown    = Column(Float, nullable=True)
    eval_sample_count = Column(Integer, default=0)
    promoted_at       = Column(DateTime, nullable=True)
    retired_at        = Column(DateTime, nullable=True)
    retire_reason     = Column(Text, nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArenaEvaluation(Base):
    __tablename__ = "arena_evaluations"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    eval_date             = Column(Date, nullable=False, index=True)
    champion_model        = Column(String(60), nullable=True)
    challenger_models_json = Column(Text, nullable=True)
    winner                = Column(String(60), nullable=True)
    promotion_triggered   = Column(Boolean, default=False)
    stats_json            = Column(Text, nullable=True)
    decision_rationale    = Column(Text, nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 22: BAYESIAN UNCERTAINTY
# ══════════════════════════════════════════════════════════════

class UncertaintyEstimate(Base):
    __tablename__ = "uncertainty_estimates"

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id           = Column(Integer, nullable=False, index=True)
    symbol                  = Column(String(20), nullable=False)
    estimate_date           = Column(Date, nullable=False)
    base_confidence         = Column(Float, nullable=True)
    uncertainty_pct         = Column(Float, nullable=True)
    adjusted_confidence     = Column(Float, nullable=True)
    epistemic_uncertainty   = Column(Float, nullable=True)
    aleatoric_uncertainty   = Column(Float, nullable=True)
    regime_familiarity      = Column(Float, nullable=True)
    feature_stability       = Column(Float, nullable=True)
    model_agreement         = Column(Float, nullable=True)
    historical_calibration  = Column(Float, nullable=True)
    similar_cases_count     = Column(Integer, default=0)
    components_json         = Column(Text, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# LAYER 23: MULTI-AGENT DECISION SYSTEM
# ══════════════════════════════════════════════════════════════

class SpecialistAgentOpinion(Base):
    __tablename__ = "specialist_agent_opinions"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    session_id    = Column(String(40), nullable=False, index=True)
    prediction_id = Column(Integer, nullable=False, index=True)
    symbol        = Column(String(20), nullable=False)
    opinion_date  = Column(Date, nullable=False)
    agent_name    = Column(String(40), nullable=False)
    direction     = Column(String(20), nullable=True)
    confidence    = Column(Float, nullable=True)
    reasoning     = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)
    weight        = Column(Float, default=1.0)
    created_at    = Column(DateTime, default=datetime.utcnow)


class ModeratorDecision(Base):
    __tablename__ = "moderator_decisions"
    __table_args__ = (UniqueConstraint("session_id", name="uq_moderator_session"),)

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    session_id           = Column(String(40), nullable=False, unique=True, index=True)
    prediction_id        = Column(Integer, nullable=False, index=True)
    symbol               = Column(String(20), nullable=False)
    decision_date        = Column(Date, nullable=False)
    final_direction      = Column(String(20), nullable=True)
    final_confidence     = Column(Float, nullable=True)
    agreement_score      = Column(Float, nullable=True)
    disagreement_score   = Column(Float, nullable=True)
    dominant_agent       = Column(String(40), nullable=True)
    minority_opinion     = Column(Text, nullable=True)
    final_rationale      = Column(Text, nullable=True)
    agents_summary_json  = Column(Text, nullable=True)
    created_at           = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 9: CHAMPION-CHALLENGER ARENA V2
# ══════════════════════════════════════════════════════════════

class P9Arena(Base):
    __tablename__ = "p9_arenas"

    id                         = Column(Integer, primary_key=True, autoincrement=True)
    arena_id                   = Column(String(40), unique=True, nullable=False, index=True)
    name                       = Column(String(100), nullable=False)
    champion_model_id          = Column(String(100), nullable=False)
    previous_champion_id       = Column(String(100), nullable=True)
    challenger_model_ids_json  = Column(Text, default="[]")
    status                     = Column(String(20), default="active")
    last_evaluated             = Column(Date, nullable=True)
    created_at                 = Column(DateTime, default=datetime.utcnow)


class P9ArenaEval(Base):
    __tablename__ = "p9_arena_evaluations"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    eval_id             = Column(String(40), unique=True, nullable=False, index=True)
    arena_id            = Column(String(40), nullable=False, index=True)
    champion_model_id   = Column(String(100), nullable=False)
    challenger_model_id = Column(String(100), nullable=False)
    eval_date           = Column(Date, nullable=False)
    champion_accuracy   = Column(Float, nullable=True)
    challenger_accuracy = Column(Float, nullable=True)
    acc_delta           = Column(Float, nullable=True)
    champion_auc        = Column(Float, nullable=True)
    challenger_auc      = Column(Float, nullable=True)
    auc_delta           = Column(Float, nullable=True)
    eval_sample_count   = Column(Integer, default=0)
    verdict             = Column(String(30), nullable=True)
    promotion_reason    = Column(Text, nullable=True)
    thresholds_json     = Column(Text, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 9: UNCERTAINTY ESTIMATES V2
# ══════════════════════════════════════════════════════════════

class P9Uncertainty(Base):
    __tablename__ = "p9_uncertainty_estimates"

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    model_id                = Column(String(100), nullable=False, index=True)
    symbol                  = Column(String(20), nullable=True)
    estimate_date           = Column(Date, nullable=False)
    base_confidence         = Column(Float, nullable=True)
    epistemic_uncertainty   = Column(Float, nullable=True)
    aleatoric_uncertainty   = Column(Float, nullable=True)
    regime_familiarity      = Column(Float, nullable=True)
    feature_stability       = Column(Float, nullable=True)
    historical_calibration  = Column(Float, nullable=True)
    composite_uncertainty   = Column(Float, nullable=True)
    final_confidence        = Column(Float, nullable=True)
    confidence_label        = Column(String(30), nullable=True)
    breakdown_json          = Column(Text, nullable=True)
    explanation             = Column(Text, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# PHASE 9: MULTI-AGENT OPINIONS V2
# ══════════════════════════════════════════════════════════════

class P9AgentOpinion(Base):
    __tablename__ = "p9_agent_opinions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    session_id      = Column(String(40), nullable=False, index=True)
    agent_name      = Column(String(40), nullable=False)
    symbol          = Column(String(20), nullable=False)
    strategy_id     = Column(String(60), nullable=True)
    direction       = Column(String(20), nullable=True)
    confidence      = Column(Float, nullable=True)
    reasoning       = Column(Text, nullable=True)
    regime_context  = Column(String(40), nullable=True)
    indicators_used = Column(Text, nullable=True)
    weight          = Column(Float, default=1.0)
    created_at      = Column(DateTime, default=datetime.utcnow)


class P9ModeratorDecision(Base):
    __tablename__ = "p9_moderator_decisions"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    session_id            = Column(String(40), unique=True, nullable=False, index=True)
    symbol                = Column(String(20), nullable=False)
    strategy_id           = Column(String(60), nullable=True)
    final_direction       = Column(String(20), nullable=True)
    final_confidence      = Column(Float, nullable=True)
    agreement_score       = Column(Float, nullable=True)
    bull_weight           = Column(Float, nullable=True)
    bear_weight           = Column(Float, nullable=True)
    neutral_weight        = Column(Float, nullable=True)
    agent_summary_json    = Column(Text, nullable=True)
    dissenting_agents_json= Column(Text, nullable=True)
    reasoning             = Column(Text, nullable=True)
    decision_date         = Column(Date, nullable=False)
    created_at            = Column(DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# STRATEGY ARENA — Self-Learning Refinement Engine
# ══════════════════════════════════════════════════════════════

class ArenaRun(Base):
    """
    One row per strategy per arena refinement round.
    Tracks the full self-learning loop: replay → grade → merge → repeat.
    """
    __tablename__ = "arena_runs"
    __table_args__ = (
        Index("ix_ar_strategy_id", "strategy_id"),
        Index("ix_ar_status",      "status"),
        Index("ix_ar_started_at",  "started_at"),
    )

    id                   = Column(Integer,    primary_key=True, autoincrement=True)
    strategy_id          = Column(String(80), nullable=False)
    strategy_name        = Column(String(120),nullable=True)
    parent_strategy_id   = Column(String(80), nullable=True)   # original strategy this descends from
    generation           = Column(Integer,    nullable=False, default=0)
    round_number         = Column(Integer,    nullable=False, default=1)

    # Replay results
    total_return_pct     = Column(Float,      nullable=True)
    max_drawdown_pct     = Column(Float,      nullable=True)
    final_value          = Column(Float,      nullable=True)
    total_trades         = Column(Integer,    nullable=True)
    win_rate             = Column(Float,      nullable=True)
    winning_days_count   = Column(Integer,    nullable=True)
    losing_days_count    = Column(Integer,    nullable=True)

    # Grading
    passes_return_gate   = Column(Boolean,    nullable=True)   # return >= 120%
    passes_drawdown_gate = Column(Boolean,    nullable=True)   # drawdown >= -25%
    passes_winrate_gate  = Column(Boolean,    nullable=True)   # win_rate >= 52%
    is_champion          = Column(Boolean,    default=False)   # passed all gates
    needs_review         = Column(Boolean,    default=False)   # failed after max rounds

    # Merge info
    donor_strategy_id    = Column(String(80), nullable=True)
    donor_strategy_name  = Column(String(120),nullable=True)
    donor_coverage_pct   = Column(Float,      nullable=True)  # % of losing days donor covered

    # Progress
    status               = Column(String(20), nullable=False, default="pending")
    # pending | running | champion | refining | needs_review | error
    status_detail        = Column(Text,       nullable=True)
    daily_results_json   = Column(Text,       nullable=True)  # JSON — sampled for UI
    winning_days_json    = Column(Text,       nullable=True)
    losing_days_json     = Column(Text,       nullable=True)

    started_at           = Column(DateTime,   nullable=True)
    completed_at         = Column(DateTime,   nullable=True)


# ══════════════════════════════════════════════════════════════
# LAYER: INDEX FUTURES (separate segment from stock DailyPrice)
# ══════════════════════════════════════════════════════════════
# DailyPrice has a hard FK to Stock.symbol, and IndexData (spot-only, no
# lot/margin/expiry concept) is used purely as a benchmark input elsewhere —
# neither fits a real futures instrument. These tables are intentionally
# parallel and self-contained so the index-futures segment can never collide
# with or be mistaken for the stock pipeline.
#
# DATA SOURCE CAVEAT (real limitation, not a bug): no free data source
# (yfinance included) carries historical NSE index FUTURES contract prices
# for a 5-year window — only the underlying SPOT index. IndexFuturesPrice is
# therefore a MODELED continuous series: spot close + a cost-of-carry basis
# (risk-free rate minus dividend yield, prorated to days-to-expiry), not real
# traded futures ticks. This is a standard, textbook futures-pricing
# approximation (F = S * e^((r-q)*T)), not fabricated data — but it is an
# approximation, and `is_synthetic=True` on every row plus this comment
# exists so nobody downstream mistakes it for real contract-level data.
class IndexFuturesContract(Base):
    """Metadata for one tradeable index future (NIFTY, BANKNIFTY, etc.)."""
    __tablename__ = "index_futures_contracts"

    id            = Column(Integer,   primary_key=True, autoincrement=True)
    index_name    = Column(String(30), nullable=False, unique=True, index=True)
    # NIFTY50 | BANKNIFTY | SENSEX | NIFTYIT | NIFTYPHARMA
    underlying_source = Column(String(20), nullable=False)
    # yfinance ticker for the underlying SPOT index (e.g. "^NSEI")
    exchange      = Column(String(10), nullable=False, default="NSE")
    lot_size      = Column(Integer,   nullable=False)
    tick_size     = Column(Float,     nullable=False, default=0.05)
    margin_pct    = Column(Float,     nullable=False, default=0.13)
    # fixed % of notional (approximates typical SPAN+exposure margin) —
    # see promotion_config-style rationale comment in index_futures_config.py
    active        = Column(Boolean,   default=True)


class IndexFuturesPrice(Base):
    """
    Daily continuous-series OHLC for one index future, per calendar month
    contract. is_synthetic is always True today (see module-level caveat
    above) — the column exists so a future switch to a real F&O data
    provider doesn't require a schema change, just is_synthetic=False rows.
    """
    __tablename__ = "index_futures_prices"
    __table_args__ = (
        UniqueConstraint("index_name", "contract_month", "date",
                          name="uq_ifp_index_month_date"),
        Index("ix_ifp_index_date", "index_name", "date"),
    )

    id             = Column(Integer,  primary_key=True, autoincrement=True)
    index_name     = Column(String(30), nullable=False, index=True)
    contract_month = Column(String(7),  nullable=False)   # "2026-07" (expiry month)
    date           = Column(Date,      nullable=False)
    expiry_date    = Column(Date,      nullable=False)     # last Thursday of contract_month
    open           = Column(Float,     nullable=True)
    high           = Column(Float,     nullable=True)
    low            = Column(Float,     nullable=True)
    close          = Column(Float,     nullable=False)
    spot_close     = Column(Float,     nullable=True)      # underlying index close, same date
    basis          = Column(Float,     nullable=True)       # futures_close - spot_close
    is_synthetic   = Column(Boolean,   nullable=False, default=True)


class IndexFuturesRoll(Base):
    """
    Records each contract-month expiry roll for a continuous series —
    needed so the backtester can apply a realistic roll cost/slippage and
    so P&L attribution can distinguish "held through a roll" from a normal
    intra-month move.
    """
    __tablename__ = "index_futures_rolls"
    __table_args__ = (
        Index("ix_ifr_index_date", "index_name", "roll_date"),
    )

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    index_name          = Column(String(30), nullable=False)
    roll_date           = Column(Date,       nullable=False)
    from_contract_month = Column(String(7),  nullable=False)
    to_contract_month   = Column(String(7),  nullable=False)
    from_close          = Column(Float,      nullable=True)
    to_close            = Column(Float,      nullable=True)
    roll_cost_pct       = Column(Float,      nullable=True)   # (to_close - from_close) / from_close
    created_at           = Column(DateTime,   default=datetime.utcnow)


class IndexFuturesFeatureValue(Base):
    """
    Computed feature values for index instruments — mirrors FeatureValue's
    shape exactly but keyed on index_name (no FK to Stock) and computed by
    a dedicated, smaller feature set (features/index_features.py) since
    volume/delivery/liquidity features that dominate the stock feature set
    don't apply to an index (no real traded volume, no delivery %).
    """
    __tablename__ = "index_futures_feature_values"
    __table_args__ = (
        UniqueConstraint("index_name", "date", "feature_name", "version",
                         name="uq_iffv_index_date_name_ver"),
        Index("ix_iffv_index_date",   "index_name", "date"),
        Index("ix_iffv_feature_name", "feature_name"),
    )

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    index_name   = Column(String(30), nullable=False)
    date         = Column(Date,       nullable=False)
    feature_name = Column(String(80), nullable=False)
    value        = Column(Float,      nullable=True)
    version      = Column(Integer,    nullable=False, default=1)
    computed_at  = Column(DateTime,   default=datetime.utcnow)


class SystemHealthCheck(Base):
    """
    GO-3: Daily 16:30 IST self-check result. One row per check run.
    The UI reads the latest row to show/hide the red failure banner.
    """
    __tablename__ = "system_health_checks"
    __table_args__ = (
        Index("ix_shc_checked_at", "checked_at"),
    )

    id              = Column(Integer,  primary_key=True, autoincrement=True)
    checked_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    prices_ok       = Column(Boolean,  nullable=False, default=False)
    shadow_ok       = Column(Boolean,  nullable=False, default=False)
    pipeline_ok     = Column(Boolean,  nullable=False, default=False)
    overall_ok      = Column(Boolean,  nullable=False, default=False)
    prices_count    = Column(Integer,  nullable=True)
    shadow_count    = Column(Integer,  nullable=True)
    failures        = Column(String(500), nullable=True)


# ══════════════════════════════════════════════════════════════
# PERSONAL PORTFOLIO — Real-money tracker (PF-2)
# ══════════════════════════════════════════════════════════════

class PortfolioInstrument(Base):
    """Registered instruments in the user's real-money portfolio."""
    __tablename__ = "portfolio_instruments"

    id                    = Column(Integer,    primary_key=True, autoincrement=True)
    ticker                = Column(String(20),  nullable=False, unique=True, index=True)
    asset_class           = Column(String(20),  nullable=False)   # equity|etf|mf|us_equity
    fund_name             = Column(String(200), nullable=True)
    amfi_code             = Column(String(20),  nullable=True, unique=True)
    isin                  = Column(String(20),  nullable=True)
    currency              = Column(String(3),   nullable=False)   # INR|USD
    target_allocation_pct = Column(Float,       nullable=True)
    risk_bucket           = Column(String(10),  nullable=False)   # core|satellite|cash
    verification_status   = Column(String(10),  nullable=False, default="pending")  # verified|pending
    created_at            = Column(DateTime,    default=datetime.utcnow)
    updated_at            = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioTransaction(Base):
    """Append-only record of every real buy/sell/rebalance/dividend/split."""
    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        Index("ix_pt_ticker_date", "ticker", "transaction_date"),
    )

    id               = Column(Integer,    primary_key=True, autoincrement=True)
    ticker           = Column(String(20), nullable=False)
    transaction_type = Column(String(10), nullable=False)   # buy|sell|rebalance|dividend|split
    quantity         = Column(Float,      nullable=False)
    price            = Column(Float,      nullable=False)
    amount           = Column(Float,      nullable=False)
    transaction_date = Column(Date,       nullable=False)
    broker           = Column(String(10), nullable=False)   # zerodha|indmoney|manual
    note             = Column(Text,       nullable=True)
    created_at       = Column(DateTime,   default=datetime.utcnow)


class PortfolioHolding(Base):
    """Derived snapshot of current holdings — refreshed after each transaction or daily."""
    __tablename__ = "portfolio_holdings"
    __table_args__ = (
        UniqueConstraint("ticker", "as_of_date", name="uq_ph_ticker_date"),
    )

    id              = Column(Integer,  primary_key=True, autoincrement=True)
    ticker          = Column(String(20), nullable=False)
    quantity        = Column(Float,    nullable=False)
    avg_cost        = Column(Float,    nullable=False)
    current_price   = Column(Float,    nullable=True)
    current_value   = Column(Float,    nullable=True)
    unrealized_pnl  = Column(Float,    nullable=True)
    realized_pnl    = Column(Float,    nullable=True)
    xirr            = Column(Float,    nullable=True)
    as_of_date      = Column(Date,     nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


class PortfolioValuation(Base):
    """Daily portfolio valuation snapshot."""
    __tablename__ = "portfolio_valuations"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    as_of_date          = Column(Date,     nullable=False, unique=True)
    total_value         = Column(Float,    nullable=False)
    total_cost          = Column(Float,    nullable=False)
    total_unrealized_pnl = Column(Float,   nullable=True)
    total_realized_pnl  = Column(Float,    nullable=True)
    cash_balance        = Column(Float,    nullable=False)
    xirr                = Column(Float,    nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)


class MutualFundNAV(Base):
    """Daily NAV records for mutual funds sourced from AMFI/MFAPI."""
    __tablename__ = "mutual_fund_navs"
    __table_args__ = (
        UniqueConstraint("amfi_code", "nav_date", name="uq_mfn_amfi_date"),
    )

    id          = Column(Integer,    primary_key=True, autoincrement=True)
    amfi_code   = Column(String(20), nullable=False)
    scheme_name = Column(String(200), nullable=True)
    nav         = Column(Float,      nullable=False)
    nav_date    = Column(Date,       nullable=False)
    source      = Column(String(10), nullable=False, default="amfi")  # amfi|mfapi
    created_at  = Column(DateTime,   default=datetime.utcnow)


class PortfolioActionLog(Base):
    """Generated reminders and action items — buys, SIP confirmations, tax checks."""
    __tablename__ = "portfolio_action_logs"

    id           = Column(Integer,    primary_key=True, autoincrement=True)
    action_type  = Column(String(20), nullable=False)   # reminder|alert|rebalance_check|tax_check
    description  = Column(Text,       nullable=True)
    due_date     = Column(Date,       nullable=True)
    status       = Column(String(10), nullable=False, default="pending")  # pending|completed|dismissed
    completed_at = Column(DateTime,   nullable=True)
    created_at   = Column(DateTime,   default=datetime.utcnow)


class ResearchSynthesis(Base):
    """
    LLM-derived daily research synthesis per symbol — the output of the
    research-to-strategy funnel (news + filings + earnings -> structured
    thesis). Always clearly labeled LLM-derived, never presented as market
    data. Every conclusion must trace to real source_event_ids; a response
    citing nonexistent IDs is rejected and never persisted here.
    """
    __tablename__ = "research_synthesis"
    __table_args__ = (
        UniqueConstraint("symbol", "synthesis_date", name="uq_rs_symbol_date"),
        Index("ix_rs_symbol",     "symbol"),
        Index("ix_rs_date",       "synthesis_date"),
    )

    id                    = Column(Integer,    primary_key=True, autoincrement=True)
    symbol                = Column(String(20), nullable=False)
    synthesis_date        = Column(Date,       nullable=False)   # point-in-time date this synthesis is valid for
    sentiment_score       = Column(Float,      nullable=False)   # -1..1
    thesis_direction      = Column(String(10), nullable=False)   # bullish|bearish|neutral
    key_catalysts         = Column(Text,       nullable=True)    # JSON list[str]
    risk_flags            = Column(Text,       nullable=True)    # JSON list[str]
    management_change_flag = Column(Boolean,   nullable=False, default=False)
    source_event_ids      = Column(Text,       nullable=False)   # JSON list[{table, id}] — every cited source
    raw_response          = Column(Text,       nullable=True)    # full LLM JSON response, for audit
    model_used            = Column(String(60), nullable=False)   # e.g. "openrouter:nousresearch/hermes-3-llama-3.1-70b:free"
    confidence            = Column(Float,      nullable=True)    # 0..1, self-reported by the LLM if provided
    created_at            = Column(DateTime,   default=datetime.utcnow)

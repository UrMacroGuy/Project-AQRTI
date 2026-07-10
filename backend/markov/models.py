"""
Markov module schema — own declarative Base, own tables (all `markov_*`).

These tables live in the same physical aqrti.db SQLite file as the rest of
AQRTI (see markov/db.py, which reuses aqrti.database.engine.get_engine()),
but are never registered against aqrti.database.models.Base and never
referenced by any file outside backend/markov/.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, Integer, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import declarative_base

MarkovBase = declarative_base()


class HMMModel(MarkovBase):
    """One row per HMM fit (versioned, weekly refit)."""
    __tablename__ = "markov_hmm_models"
    __table_args__ = (
        Index("ix_markov_hmm_models_active", "is_active"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    fit_date       = Column(Date, nullable=False)
    n_states       = Column(Integer, nullable=False, default=3)
    window_days    = Column(Integer, nullable=False, default=252)
    means_json     = Column(Text, nullable=False)
    covars_json    = Column(Text, nullable=False)
    transmat_json  = Column(Text, nullable=False)
    startprob_json = Column(Text, nullable=False)
    bic_score      = Column(Float, nullable=True)
    version        = Column(Integer, nullable=False, default=1)
    is_active      = Column(Boolean, default=True)
    trained_at     = Column(DateTime, default=datetime.utcnow)


class HMMRegimeDaily(MarkovBase):
    """Daily latent-regime assignment from the active HMM (market-wide, NIFTY-based)."""
    __tablename__ = "markov_hmm_regime_daily"
    __table_args__ = (
        UniqueConstraint("date", name="uq_markov_hmm_regime_date"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    date           = Column(Date, nullable=False, unique=True, index=True)
    regime_class   = Column(Integer, nullable=False)     # 0..K-1
    confidence_pct = Column(Float, nullable=False)        # 0-100
    state_label    = Column(String(20), nullable=True)    # "BULL"|"BEAR"|"SIDEWAYS" (mapped)
    model_version  = Column(Integer, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)


class MarkovChainDaily(MarkovBase):
    """Daily observable 3-state (Bull/Bear/Sideways) regime label + transition-matrix-derived bias."""
    __tablename__ = "markov_chain_daily"
    __table_args__ = (
        UniqueConstraint("date", name="uq_markov_chain_date"),
    )

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    date                = Column(Date, nullable=False, unique=True, index=True)
    regime_state         = Column(String(12), nullable=False)   # BULL|BEAR|SIDEWAYS
    regime_bias          = Column(Float, nullable=True)          # P(Bull) - P(Bear), stationary dist
    regime_persistence    = Column(Float, nullable=True)          # diagonal entry (stickiness)
    transition_matrix_json = Column(Text, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)


class MarkovStrategy(MarkovBase):
    """
    Standalone strategy population for Markov-powered strategies.
    Deliberately NOT StrategyV2 — separate table, separate lifecycle,
    separate promotion/backtest logic. Never joined against strategies_v2.
    """
    __tablename__ = "markov_strategies"
    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_markov_strategy_id"),
        Index("ix_markov_strategies_family", "family"),
        Index("ix_markov_strategies_status", "status"),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id      = Column(String(40), nullable=False, unique=True)
    name             = Column(String(120), nullable=True)
    family           = Column(String(30), nullable=False)   # markov_regime|markov_hmm|markov_pairs
    params_json      = Column(Text, nullable=False)          # serialized rule/threshold params
    status           = Column(String(20), nullable=False, default="candidate")

    # Backtest metrics (independent walk-forward, never mixed with StrategyV2's)
    sharpe           = Column(Float, nullable=True)
    max_drawdown     = Column(Float, nullable=True)
    win_rate         = Column(Float, nullable=True)
    trade_count      = Column(Integer, nullable=True, default=0)
    regime_compatibility = Column(Float, nullable=True)

    backtest_start   = Column(Date, nullable=True)
    backtest_end     = Column(Date, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MarkovWatchlistSymbol(MarkovBase):
    """Symbols the Markov module runs against (independent of the main universe list)."""
    __tablename__ = "markov_watchlist"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_markov_watchlist_symbol"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    symbol     = Column(String(20), nullable=False, unique=True)
    added_at   = Column(DateTime, default=datetime.utcnow)

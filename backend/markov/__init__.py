"""
AQRTI Markov Module — fully isolated from the main strategy/algo pipeline.

Design contract (do not violate):
  - Owns its own SQLAlchemy declarative Base (MarkovBase) and its own tables,
    all prefixed `markov_*` in the schema.
  - Shares the SAME physical database file (aqrti.db) as the rest of AQRTI —
    reuses aqrti.database.engine.get_engine() for the connection — but never
    imports aqrti.database.models.Base, StrategyV2, the DSL, the strategy
    generator, the backtester, or the fitness engine.
  - Reads DailyPrice / IndexData tables (existing OHLCV data) strictly
    read-only, via plain SQL through the shared engine.
  - Every entry point (boot step, scheduler job, API route) catches its own
    exceptions so a Markov bug can never crash or block the main AQRTI boot
    sequence, scheduler, or UI.
  - Has its own API router (/api/v1/markov/*) and its own UI page — it does
    not appear on any existing AQRTI page.
"""

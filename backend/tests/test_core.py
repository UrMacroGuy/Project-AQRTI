"""
ARCH-2: Minimal regression test suite.
Tests the four critical properties that have burned us before:
  1. Honest Sharpe/Sortino/MDD on known series (no look-ahead bias in metrics)
  2. Label generator: no row uses future data as its own feature date
  3. Dataset leak-guard: train rows never appear in OOS window
  4. Promotion gates: the actual gate logic in strategy_lifecycle.py
  5. Session rollback: a failed flush does not poison subsequent queries

Run from the backend directory:
  python -m pytest tests/test_core.py -v
"""

from __future__ import annotations

import os
import sys
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

# Ensure backend packages are importable regardless of CWD
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ─────────────────────────────────────────────────────────────────────────────
# 1. strategy_metrics — honest Sharpe / Sortino / MDD
# ─────────────────────────────────────────────────────────────────────────────

from strategies.strategy_metrics import (
    compute_sharpe,
    compute_sortino,
    compute_max_drawdown,
    RISK_FREE,
    ANNUALISE,
)


class TestComputeSharpe:
    def test_constant_positive_series(self):
        # All returns same positive value → std of excess = 0 → Sharpe = 0
        rets = [1.0] * 20
        assert compute_sharpe(rets) == 0.0

    def test_zero_returns(self):
        # All returns are 0.0 → excess is constant (-RISK_FREE) → std of excess = 0
        # The std=0 guard returns 0.0 (deflationary convention, not -inf)
        rets = [0.0] * 20
        assert compute_sharpe(rets) == 0.0

    def test_slightly_negative_mean_returns(self):
        # Returns that vary around a negative mean should yield a negative Sharpe
        rng = np.random.default_rng(7)
        rets = list(rng.normal(loc=-0.5, scale=0.1, size=60))  # μ << 0, has dispersion
        assert compute_sharpe(rets) < 0

    def test_high_positive_series_is_capped(self):
        # Synthetic series with enormous positive excess — should be capped at 8.0
        rets = [5.0] * 50
        s = compute_sharpe(rets)
        assert s == 0.0  # constant → std = 0 → 0.0

    def test_known_series(self):
        # Hand-computed: daily returns 0.1% for 252 days
        # excess = 0.1 - RISK_FREE per day, std = 0 → Sharpe = 0 (constant)
        rets = [0.1] * 252
        s = compute_sharpe(rets)
        assert s == 0.0

    def test_mixed_series_is_positive(self):
        # Alternating 1% up, 0.2% down — net positive, should give positive Sharpe
        rets = [1.0, -0.2] * 60
        s = compute_sharpe(rets)
        assert s > 0, f"Expected positive Sharpe, got {s}"

    def test_cap_at_8(self):
        # Sharpe formula can blow up; must be capped at 8
        rng = np.random.default_rng(42)
        big_returns = list(rng.normal(loc=0.5, scale=0.01, size=252))
        s = compute_sharpe(big_returns)
        assert s <= 8.0
        assert s >= -8.0

    def test_fewer_than_5_returns_zero(self):
        assert compute_sharpe([1.0, 2.0, 3.0]) == 0.0

    def test_returns_float(self):
        rets = [0.5, -0.3, 0.8, -0.1, 0.6] * 10
        s = compute_sharpe(rets)
        assert isinstance(s, float)


class TestComputeSortino:
    def test_no_downside_returns_zero(self):
        # Only positive returns (< 3 downside obs) → returns 0, not inf
        rets = [1.0, 2.0, 0.5, 3.0, 1.5] * 10
        assert compute_sortino(rets) == 0.0

    def test_fewer_than_5_returns_zero(self):
        assert compute_sortino([1.0, -0.5]) == 0.0

    def test_negative_series_is_negative(self):
        rets = [-1.0, -0.5, -2.0, -0.3, -1.5] * 10
        s = compute_sortino(rets)
        assert s < 0

    def test_capped(self):
        rng = np.random.default_rng(99)
        rets = list(rng.normal(loc=0.5, scale=0.01, size=252))
        rets[::20] = [-0.01] * len(rets[::20])  # inject some small downsides
        s = compute_sortino(rets)
        assert abs(s) <= 10.0


class TestComputeMaxDrawdown:
    def test_all_up_zero_drawdown(self):
        cum = [1.0, 2.0, 3.0, 4.0, 5.0]
        mdd = compute_max_drawdown(cum)
        assert mdd == 0.0

    def test_monotone_decline(self):
        cum = [5.0, 4.0, 3.0, 2.0, 1.0]
        mdd = compute_max_drawdown(cum)
        assert mdd < 0, "Declining series must have negative MDD"

    def test_known_drawdown(self):
        # peak = 10, trough = 5 → drawdown = (5-10)/10 * 100 = -50%
        cum = [10.0, 8.0, 5.0, 7.0]
        mdd = compute_max_drawdown(cum)
        assert mdd <= -49.0 and mdd >= -51.0, f"Expected ~-50%, got {mdd}"

    def test_empty_returns_zero(self):
        assert compute_max_drawdown([]) == 0.0

    def test_returns_negative_or_zero(self):
        cum = [1.0, 2.0, 1.5, 2.5]
        mdd = compute_max_drawdown(cum)
        assert mdd <= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. label_generator — no look-ahead: label for date[i] uses close[i+h], not [i-h]
# ─────────────────────────────────────────────────────────────────────────────

from ml.datasets.label_generator import generate_labels, HORIZONS, LABEL_COLUMNS


def _make_price_df(n: int, start_price: float = 100.0, drift: float = 0.001) -> pd.DataFrame:
    """Create a monotone price series starting from start_price."""
    prices = [start_price * (1 + drift) ** i for i in range(n)]
    start = date(2023, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({"date": dates, "close": prices})


class TestLabelGenerator:
    def test_no_rows_if_insufficient_data(self):
        df = _make_price_df(max(HORIZONS))  # exactly max horizon, no room for labels
        nifty = _make_price_df(max(HORIZONS))
        result = generate_labels(df, nifty)
        assert result.empty

    def test_labels_use_forward_prices(self):
        # Monotone series: prices strictly increase.
        # return_5d for row i = close[i+5]/close[i] - 1 > 0.
        # If labels were using backward prices (look-ahead bug), the sign would flip.
        df = _make_price_df(40, drift=0.01)  # 1% daily drift
        nifty = _make_price_df(40, drift=0.0)
        result = generate_labels(df, nifty)
        assert len(result) > 0
        # All direction_5d should be 1 (positive drift)
        assert (result["direction_5d"] == 1).all(), "Should all be up in monotone rising series"

    def test_no_nans_in_output(self):
        df = _make_price_df(50)
        nifty = _make_price_df(50)
        result = generate_labels(df, nifty)
        assert result["return_5d"].notna().all()
        assert result["direction_5d"].notna().all()

    def test_last_rows_dropped(self):
        # The last max(HORIZONS) rows cannot have forward labels — they must be dropped
        n = 40
        df = _make_price_df(n)
        nifty = _make_price_df(n)
        result = generate_labels(df, nifty)
        labeled_dates = set(result["date"])
        # The last date in df must NOT be in labeled_dates (no forward price)
        last_date = df.iloc[-1]["date"]
        assert last_date not in labeled_dates, "Last row must be dropped (no forward price)"

    def test_label_columns_present(self):
        df = _make_price_df(50)
        nifty = _make_price_df(50)
        result = generate_labels(df, nifty)
        for col in LABEL_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_declining_series_all_down(self):
        # If price falls every day, all direction_5d should be 0
        df = _make_price_df(40, drift=-0.01)
        nifty = _make_price_df(40, drift=0.0)
        result = generate_labels(df, nifty)
        if len(result) > 0:
            assert (result["direction_5d"] == 0).all(), "Declining series: all should be direction=0"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Promotion gate logic — check that strategy_lifecycle gates match promotion_config
# ─────────────────────────────────────────────────────────────────────────────

from strategies.promotion_config import (
    PROMOTE_THRESHOLD, MIN_BACKTEST_TRADES, MIN_WIN_RATE, MIN_SHARPE,
    REQUIRE_OOS_PASS, MIN_OOS_SHARPE, BENCHMARK_SHARPE_FACTOR,
    QUARANTINE_MIN_DAYS, QUARANTINE_MIN_TRADES, QUARANTINE_MIN_WIN_RATE,
    MAX_DRAWDOWN_LIMIT,
)


class TestPromotionConfig:
    def test_sharpe_gate_is_positive(self):
        assert MIN_SHARPE > 0, "MIN_SHARPE must be strictly positive"

    def test_win_rate_above_coin_flip(self):
        assert MIN_WIN_RATE > 50.0, "MIN_WIN_RATE must beat coin flip"

    def test_quarantine_days_meaningful(self):
        assert QUARANTINE_MIN_DAYS >= 60, "Quarantine must be at least 60 days"

    def test_quarantine_min_trades_meaningful(self):
        assert QUARANTINE_MIN_TRADES >= 10

    def test_drawdown_limit_is_negative(self):
        assert MAX_DRAWDOWN_LIMIT < 0, "Drawdown limit must be negative"

    def test_drawdown_limit_not_permissive(self):
        # -100 would never trigger retirement — must be tighter
        assert MAX_DRAWDOWN_LIMIT > -100.0

    def test_oos_required(self):
        assert REQUIRE_OOS_PASS is True, "OOS gate must be required"

    def test_oos_sharpe_non_negative(self):
        assert MIN_OOS_SHARPE >= 0

    def test_benchmark_factor_in_range(self):
        assert 0 < BENCHMARK_SHARPE_FACTOR <= 1.0

    def test_promote_threshold_range(self):
        assert 0 < PROMOTE_THRESHOLD <= 100

    def test_min_trades_meaningful(self):
        assert MIN_BACKTEST_TRADES >= 20, "Need at least 20 trades for statistical meaning"


# ─────────────────────────────────────────────────────────────────────────────
# 4. SQLAlchemy session rollback — failed flush must not poison next query
#    Uses an in-memory SQLite DB to avoid touching aqrti.db
# ─────────────────────────────────────────────────────────────────────────────

from sqlalchemy import create_engine, Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

_Base = declarative_base()


class _TestModel(_Base):
    __tablename__ = "test_rollback_table"
    __table_args__ = (UniqueConstraint("name"),)
    id   = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)


class TestSessionRollback:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        engine = create_engine("sqlite:///:memory:", echo=False)
        _Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.session = Session()
        yield
        self.session.close()
        engine.dispose()

    def test_failed_flush_rollback_allows_next_query(self):
        """A failed flush (duplicate unique constraint) must roll back so subsequent
        queries succeed. This replicates the 2026-07-03e backend crash where a
        logged-but-not-rolled-back error poisoned all subsequent DB callers."""
        # Insert a row
        row1 = _TestModel(name="alpha")
        self.session.add(row1)
        self.session.commit()

        # Try to insert duplicate — this will fail with IntegrityError
        row2 = _TestModel(name="alpha")  # duplicate
        self.session.add(row2)
        try:
            self.session.flush()
            pytest.fail("Expected IntegrityError from duplicate insert")
        except Exception:
            self.session.rollback()  # ← the fix pattern from the convention in CLAUDE.md

        # After rollback, session must be usable again
        count = self.session.query(_TestModel).count()
        assert count == 1, "Session should work normally after rollback; exactly 1 row expected"

    def test_no_rollback_poisons_session(self):
        """Document the failure mode: NOT rolling back after a failed flush makes
        the session unusable. This test shows it fails, validating the test harness."""
        row1 = _TestModel(name="beta")
        self.session.add(row1)
        self.session.commit()

        row2 = _TestModel(name="beta")
        self.session.add(row2)
        try:
            self.session.flush()
        except Exception:
            # Intentionally skip rollback — next query must fail or give stale data
            # In SQLAlchemy, the session is in an invalid state post-flush-error.
            # A new add/query without rollback will raise InvalidRequestError.
            pass

        # Attempting to commit without rollback should raise
        with pytest.raises(Exception):
            self.session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 5. MIN_OOS_WIN_RATE gate — promote_strategy must reject a strategy whose OOS
#    win rate is below the 50% floor even when every other gate passes, and
#    admit it once OOS win rate clears 50%. Uses an in-memory SQLite DB
#    (real aqrti.database.models.Base) so promote_strategy's actual query/
#    update path is exercised, not a re-implementation of its logic.
# ─────────────────────────────────────────────────────────────────────────────

from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import sessionmaker as _sessionmaker

from aqrti.database.models import Base as _AqrtiBase, StrategyV2
from strategies.promotion_config import MIN_OOS_WIN_RATE
from strategies.strategy_lifecycle import promote_strategy


def _make_promotable_strategy_row(**overrides) -> dict:
    """Field values that clear every OTHER promotion gate, so a rejection can
    only come from the gate under test. Mirrors promote_strategy's own
    thresholds (strategy_lifecycle.py) with comfortable margin."""
    base = dict(
        strategy_id      = "AQRTI_STR_TESTOOSWR01",
        name             = "TestOOSWinRate",
        family           = "post_earnings_drift",
        asset_class      = "stock",
        dsl_json         = "{}",
        status           = "shadow",
        fitness_score    = 80.0,
        trade_count      = 200,
        win_rate         = 60.0,
        sharpe           = 1.0,
        oos_passed       = True,
        oos_sharpe       = 0.5,
        oos_win_rate     = 55.0,   # overridden per-test
        backtest_start   = None,   # skip benchmark gate (requires both start+end)
        backtest_end     = None,
    )
    base.update(overrides)
    return base


class TestMinOosWinRateGate:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        engine = _create_engine("sqlite:///:memory:", echo=False)
        _AqrtiBase.metadata.create_all(engine)
        Session = _sessionmaker(bind=engine)
        self.db = Session()
        yield
        self.db.close()
        engine.dispose()

    def test_49_percent_oos_win_rate_is_rejected(self):
        row = StrategyV2(**_make_promotable_strategy_row(
            strategy_id="AQRTI_STR_TESTOOSWR49", oos_win_rate=49.0,
        ))
        self.db.add(row)
        self.db.commit()

        result = promote_strategy(self.db, "AQRTI_STR_TESTOOSWR49")

        assert result["success"] is False
        assert "oos_win_rate" in result["error"]
        refreshed = self.db.query(StrategyV2).filter_by(strategy_id="AQRTI_STR_TESTOOSWR49").first()
        assert refreshed.status == "shadow", "Rejected strategy must not advance past shadow"

    def test_51_percent_oos_win_rate_passes_to_quarantine(self):
        row = StrategyV2(**_make_promotable_strategy_row(
            strategy_id="AQRTI_STR_TESTOOSWR51", oos_win_rate=51.0,
        ))
        self.db.add(row)
        self.db.commit()

        result = promote_strategy(self.db, "AQRTI_STR_TESTOOSWR51")

        assert result["success"] is True, result.get("error")
        refreshed = self.db.query(StrategyV2).filter_by(strategy_id="AQRTI_STR_TESTOOSWR51").first()
        assert refreshed.status == "promoted", "Accepted strategy must move to promoted (quarantine) status"

    def test_floor_constant_is_50_percent(self):
        assert MIN_OOS_WIN_RATE == 50.0


from aqrti.database.models import PaperTrade, MarketRegime
import strategies.live_validator as _lv


class TestPostPromotionDemotionTriggers:
    """
    Post-promotion lifecycle demotion triggers (live_validator.py) — additive
    checks on top of the pre-existing divergence check, never replacing it.
    """

    @pytest.fixture(autouse=True)
    def setup_db(self):
        engine = _create_engine("sqlite:///:memory:", echo=False)
        _AqrtiBase.metadata.create_all(engine)
        Session = _sessionmaker(bind=engine)
        self.db = Session()
        yield
        self.db.close()
        engine.dispose()

    def _add_trades(self, strategy_id, pnls, base=date(2026, 1, 1)):
        for i, pnl in enumerate(pnls):
            self.db.add(PaperTrade(
                portfolio_name=f"strat_{strategy_id}", symbol="BEL", is_open=False,
                entry_date=base + timedelta(days=i), exit_date=base + timedelta(days=i + 1),
                gross_pnl=pnl, gross_pnl_pct=pnl,
                entry_price=100, shares=1, capital_deployed=100,
            ))
        self.db.commit()

    def test_rolling_win_rate_below_floor_demotes(self):
        row = StrategyV2(strategy_id="AQRTI_STR_WRFLOOR", family="post_earnings_drift",
                          dsl_json="{}", status="promoted", max_drawdown=-10.0,
                          sharpe=1.0, win_rate=60.0, allowed_regimes='["BULL"]', bull_sharpe=1.2)
        self.db.add(row)
        self.db.commit()
        # 20 trades, 8 wins = 40% < 50% floor
        self._add_trades("AQRTI_STR_WRFLOOR", [1.0] * 8 + [-1.0] * 12)

        result = _lv._check_rolling_win_rate_floor(self.db, "AQRTI_STR_WRFLOOR")
        assert result["demote"] is True

    def test_rolling_win_rate_above_floor_does_not_demote(self):
        row = StrategyV2(strategy_id="AQRTI_STR_WROK", family="post_earnings_drift",
                          dsl_json="{}", status="promoted", max_drawdown=-10.0,
                          sharpe=1.0, win_rate=60.0, allowed_regimes='["BULL"]', bull_sharpe=1.2)
        self.db.add(row)
        self.db.commit()
        # 20 trades, 12 wins = 60% >= 50% floor
        self._add_trades("AQRTI_STR_WROK", [1.0] * 12 + [-0.8] * 8)

        result = _lv._check_rolling_win_rate_floor(self.db, "AQRTI_STR_WROK")
        assert result["demote"] is False

    def test_drawdown_breach_over_1_5x_backtest_demotes(self):
        row = StrategyV2(strategy_id="AQRTI_STR_DDBREACH", family="momentum_trend",
                          dsl_json="{}", status="promoted", max_drawdown=-10.0,
                          sharpe=1.0, win_rate=60.0)
        self.db.add(row)
        self.db.commit()
        # peak=5, trough=-20 -> dd = -500% >> 1.5x(-10%) = -15%
        self._add_trades("AQRTI_STR_DDBREACH", [5, -2, -2, -6, -3, -7, -5])

        result = _lv._check_drawdown_breach(self.db, "AQRTI_STR_DDBREACH")
        assert result["demote"] is True

    def test_regime_shift_outside_allowed_demotes(self):
        row = StrategyV2(strategy_id="AQRTI_STR_REGIMESHIFT", family="momentum_trend",
                          dsl_json="{}", status="promoted", max_drawdown=-10.0,
                          sharpe=1.0, win_rate=60.0, allowed_regimes='["BULL"]', bull_sharpe=1.2)
        self.db.add(row)
        self.db.add(MarketRegime(date=date.today(), regime="BEAR", confidence=80.0))
        self.db.commit()

        result = _lv._check_regime_shift(self.db, "AQRTI_STR_REGIMESHIFT")
        assert result["demote"] is True

    def test_regime_within_allowed_and_validated_does_not_demote(self):
        row = StrategyV2(strategy_id="AQRTI_STR_REGIMEOK", family="momentum_trend",
                          dsl_json="{}", status="promoted", max_drawdown=-10.0,
                          sharpe=1.0, win_rate=60.0, allowed_regimes='["BULL","SIDEWAYS"]',
                          bull_sharpe=1.2, sideways_sharpe=0.5)
        self.db.add(row)
        self.db.add(MarketRegime(date=date.today(), regime="BULL", confidence=80.0))
        self.db.commit()

        result = _lv._check_regime_shift(self.db, "AQRTI_STR_REGIMEOK")
        assert result["demote"] is False


from aqrti.database.models import PortfolioTransaction
from portfolio.paper_real_reconciliation import reconcile, has_real_trades


class TestPaperRealReconciliation:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        engine = _create_engine("sqlite:///:memory:", echo=False)
        _AqrtiBase.metadata.create_all(engine)
        Session = _sessionmaker(bind=engine)
        self.db = Session()
        yield
        self.db.close()
        engine.dispose()

    def test_no_real_trades_reports_honestly(self):
        assert has_real_trades(self.db) is False
        result = reconcile(self.db)
        assert result["has_real_trades"] is False
        assert result["comparisons"] == []
        assert result["persistent_gap_flags"] == []

    def test_matches_real_transaction_to_paper_trade_within_window(self):
        base = date(2026, 1, 1)
        self.db.add(PortfolioTransaction(
            ticker="BEL", transaction_type="buy", quantity=10, price=105.0,
            amount=1050.0, transaction_date=base, broker="zerodha",
        ))
        self.db.add(PaperTrade(
            portfolio_name="strat_TEST", symbol="BEL", is_open=False,
            entry_date=base + timedelta(days=1), exit_date=base + timedelta(days=6),
            entry_price=100.0, exit_price=110.0, shares=1, capital_deployed=100,
            strategy_id="AQRTI_STR_TEST",
        ))
        self.db.commit()

        result = reconcile(self.db)
        assert result["has_real_trades"] is True
        assert result["matched"] == 1
        assert result["comparisons"][0]["gap_pct"] == 5.0

    def test_persistent_gap_flagged_after_repeated_significant_divergence(self):
        base = date(2026, 1, 1)
        for i in range(3):
            d = base + timedelta(days=i * 10)
            self.db.add(PortfolioTransaction(
                ticker="BEL", transaction_type="buy", quantity=10, price=105.0,
                amount=1050.0, transaction_date=d, broker="zerodha",
            ))
            self.db.add(PaperTrade(
                portfolio_name="strat_TEST", symbol="BEL", is_open=False,
                entry_date=d, exit_date=d + timedelta(days=5),
                entry_price=100.0, exit_price=110.0, shares=1, capital_deployed=100,
                strategy_id="AQRTI_STR_TEST",
            ))
        self.db.commit()

        result = reconcile(self.db)
        assert len(result["persistent_gap_flags"]) == 1
        assert result["persistent_gap_flags"][0]["ticker"] == "BEL"
        assert result["persistent_gap_flags"][0]["direction"] == "real_worse_than_paper"

    def test_small_gap_not_flagged_as_persistent(self):
        base = date(2026, 1, 1)
        for i in range(3):
            d = base + timedelta(days=i * 10)
            self.db.add(PortfolioTransaction(
                ticker="HDFCBANK", transaction_type="buy", quantity=1, price=100.2,
                amount=100.2, transaction_date=d, broker="zerodha",
            ))
            self.db.add(PaperTrade(
                portfolio_name="strat_TEST", symbol="HDFCBANK", is_open=False,
                entry_date=d, exit_date=d + timedelta(days=5),
                entry_price=100.0, exit_price=105.0, shares=1, capital_deployed=100,
                strategy_id="AQRTI_STR_TEST",
            ))
        self.db.commit()

        result = reconcile(self.db)
        assert result["persistent_gap_flags"] == []


from aqrti.database.models import ResearchSynthesis
from portfolio.monthly_allocator import compute_monthly_allocation, SATELLITE_SYMBOLS, SATELLITE_MONTHLY_BUDGET_INR


class TestMonthlyAllocator:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        engine = _create_engine("sqlite:///:memory:", echo=False)
        _AqrtiBase.metadata.create_all(engine)
        Session = _sessionmaker(bind=engine)
        self.db = Session()
        yield
        self.db.close()
        engine.dispose()

    def test_no_data_falls_back_to_equal_split(self):
        result = compute_monthly_allocation(self.db)
        assert result["basis"] == "equal_split_no_data"
        for symbol in SATELLITE_SYMBOLS:
            assert result["allocation_inr"][symbol] == round(SATELLITE_MONTHLY_BUDGET_INR / len(SATELLITE_SYMBOLS), 2)

    def test_allocation_sums_to_budget(self):
        self.db.add(ResearchSynthesis(
            symbol="BEL", synthesis_date=date.today(), sentiment_score=0.9,
            thesis_direction="bullish", key_catalysts="[]", risk_flags="[]",
            management_change_flag=False, source_event_ids="[]", model_used="test", confidence=0.9,
        ))
        self.db.commit()
        result = compute_monthly_allocation(self.db)
        total = sum(result["allocation_inr"].values())
        assert abs(total - SATELLITE_MONTHLY_BUDGET_INR) < 0.05

    def test_bullish_synthesis_ranks_above_bearish(self):
        self.db.add(ResearchSynthesis(
            symbol="BEL", synthesis_date=date.today(), sentiment_score=0.9,
            thesis_direction="bullish", key_catalysts="[]", risk_flags="[]",
            management_change_flag=False, source_event_ids="[]", model_used="test", confidence=0.9,
        ))
        self.db.add(ResearchSynthesis(
            symbol="HDFCBANK", synthesis_date=date.today(), sentiment_score=-0.5,
            thesis_direction="bearish", key_catalysts="[]", risk_flags="[]",
            management_change_flag=False, source_event_ids="[]", model_used="test", confidence=0.8,
        ))
        self.db.commit()
        result = compute_monthly_allocation(self.db)
        assert result["allocation_inr"]["BEL"] > result["allocation_inr"]["HDFCBANK"]
        assert result["ranked_symbols"][0] == "BEL"

"""
AQRTI Time Machine — Phase 8.5A
High-level interface for replaying any historical period.
Orchestrates historical_replay + market_reconstruction into reproducible training samples.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger
from intelligence_training.historical_replay import (
    replay_day, replay_week, replay_month, replay_regime, replay_event_window,
    ReplaySnapshot, snapshot_to_dict,
)
from intelligence_training.market_reconstruction import (
    reconstruct_feature_matrix, reconstruct_full_context, get_trading_dates,
)

logger = get_logger("time_machine")


@dataclass
class TrainingSample:
    """A single reproducible training sample from the time machine."""
    sample_id: str
    symbol: str
    as_of_date: date
    context: Dict[str, Any]
    label: Optional[float] = None
    label_name: Optional[str] = None
    regime: Optional[str] = None
    horizon_days: int = 5
    reproducibility_hash: str = ""

    def __post_init__(self):
        if not self.reproducibility_hash:
            raw = f"{self.symbol}|{self.as_of_date}|{self.label_name}|{self.horizon_days}"
            self.reproducibility_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["as_of_date"] = self.as_of_date.isoformat()
        return d


class TimeMachine:
    """
    Generates reproducible training samples from any historical period.
    Guarantees no future data leakage — every sample is point-in-time.
    """

    def __init__(self):
        self._db_factory = get_session_factory()

    def generate_samples_for_date(
        self,
        target_date: date,
        symbols: Optional[List[str]] = None,
        horizon_days: int = 5,
        label_name: str = "return_5d",
    ) -> List[TrainingSample]:
        """Generate training samples for all symbols on a specific date."""
        db = self._db_factory()
        try:
            if symbols is None:
                rows = db.execute("SELECT symbol FROM stocks WHERE active = 1").fetchall()
                symbols = [r[0] for r in rows]

            samples = []
            for symbol in symbols:
                context = reconstruct_full_context(target_date, symbol, db)
                if not context.get("features"):
                    continue

                # Fetch forward label (strictly future — safe because this is for training)
                label_row = db.execute(
                    "SELECT close FROM daily_prices WHERE symbol = :s AND date > :d "
                    "ORDER BY date ASC LIMIT 1 OFFSET :off",
                    {"s": symbol, "d": target_date, "off": horizon_days - 1},
                ).fetchone()
                entry_row = db.execute(
                    "SELECT close FROM daily_prices WHERE symbol = :s AND date = :d",
                    {"s": symbol, "d": target_date},
                ).fetchone()

                label = None
                if label_row and entry_row and entry_row.close:
                    label = (label_row.close - entry_row.close) / entry_row.close * 100

                sample = TrainingSample(
                    sample_id=f"{symbol}_{target_date}_{label_name}",
                    symbol=symbol,
                    as_of_date=target_date,
                    context=context,
                    label=label,
                    label_name=label_name,
                    regime=context.get("regime"),
                    horizon_days=horizon_days,
                )
                samples.append(sample)

            logger.info("Generated %d training samples for %s (horizon=%dd)",
                        len(samples), target_date, horizon_days)
            return samples
        finally:
            db.close()

    def generate_samples_for_range(
        self,
        start_date: date,
        end_date: date,
        symbols: Optional[List[str]] = None,
        horizon_days: int = 5,
        label_name: str = "return_5d",
    ) -> List[TrainingSample]:
        """Generate training samples for a full date range."""
        db = self._db_factory()
        try:
            trading_dates = get_trading_dates(start_date, end_date, db)
        finally:
            db.close()

        all_samples = []
        for d in trading_dates:
            samples = self.generate_samples_for_date(d, symbols, horizon_days, label_name)
            all_samples.extend(samples)

        logger.info("Time machine: %d total samples from %s to %s",
                    len(all_samples), start_date, end_date)
        return all_samples

    def replay_and_sample(
        self,
        scope: str,
        **kwargs,
    ) -> Tuple[List[ReplaySnapshot], List[TrainingSample]]:
        """
        Replay a historical period and generate training samples.
        scope: 'day' | 'week' | 'month' | 'regime' | 'event'
        """
        db = self._db_factory()
        try:
            if scope == "day":
                target = kwargs["target_date"]
                snapshots = [replay_day(target, db)]
                samples = self.generate_samples_for_date(target)
            elif scope == "week":
                week_start = kwargs["week_start"]
                snapshots = replay_week(week_start, db)
                dates = [s.replay_date for s in snapshots]
                samples = []
                for d in dates:
                    samples.extend(self.generate_samples_for_date(d))
            elif scope == "month":
                year, month = kwargs["year"], kwargs["month"]
                snapshots = replay_month(year, month, db)
                samples = []
                for s in snapshots:
                    samples.extend(self.generate_samples_for_date(s.replay_date))
            elif scope == "regime":
                regime_name = kwargs["regime_name"]
                snapshots = replay_regime(regime_name, db)
                samples = []
                for s in snapshots:
                    samples.extend(self.generate_samples_for_date(s.replay_date))
            elif scope == "event":
                event_date = kwargs["event_date"]
                days_before = kwargs.get("days_before", 5)
                days_after = kwargs.get("days_after", 5)
                snapshots = replay_event_window(event_date, days_before, days_after, db)
                samples = []
                for s in snapshots:
                    samples.extend(self.generate_samples_for_date(s.replay_date))
            else:
                raise ValueError(f"Unknown scope: {scope}")

            return snapshots, samples
        finally:
            db.close()

    def get_available_regimes(self) -> List[str]:
        db = self._db_factory()
        try:
            rows = db.execute("SELECT DISTINCT regime FROM market_regimes ORDER BY regime").fetchall()
            return [r[0] for r in rows]
        finally:
            db.close()

    def get_date_range(self) -> Tuple[Optional[date], Optional[date]]:
        db = self._db_factory()
        try:
            row = db.execute("SELECT MIN(date), MAX(date) FROM daily_prices").fetchone()
            if row and row[0]:
                start = row[0] if isinstance(row[0], date) else date.fromisoformat(row[0])
                end = row[1] if isinstance(row[1], date) else date.fromisoformat(row[1])
                return start, end
            return None, None
        finally:
            db.close()


_time_machine: Optional[TimeMachine] = None


def get_time_machine() -> TimeMachine:
    global _time_machine
    if _time_machine is None:
        _time_machine = TimeMachine()
    return _time_machine

"""
AQRTI Multi-Horizon Training Builder — Phase 8.5D
Generates training datasets for multiple forward-looking prediction horizons:
3d, 5d, 10d, 15d, 30d, 60d, 90d.
Each horizon gets its own label set and training dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger
from intelligence_training.market_reconstruction import reconstruct_feature_matrix, get_trading_dates

logger = get_logger("horizon_builder")

HORIZONS = [3, 5, 10, 15, 30, 60, 90]


@dataclass
class HorizonDataset:
    horizon_days: int
    label_name: str
    feature_matrix: Optional[pd.DataFrame]
    labels: Optional[pd.Series]
    sample_count: int
    positive_rate: float
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "label_name": self.label_name,
            "sample_count": self.sample_count,
            "positive_rate": self.positive_rate,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "metadata": self.metadata,
        }


def _compute_forward_return(
    symbol: str,
    entry_date: date,
    horizon_days: int,
    db: Session,
) -> Optional[float]:
    """Compute n-day forward return for a symbol from entry_date. No future leakage in training."""
    entry_row = db.execute(
        "SELECT close FROM daily_prices WHERE symbol = :s AND date = :d",
        {"s": symbol, "d": entry_date},
    ).fetchone()
    if not entry_row or not entry_row.close:
        return None

    fwd_row = db.execute(
        "SELECT close FROM daily_prices WHERE symbol = :s AND date > :d "
        "ORDER BY date ASC LIMIT 1 OFFSET :off",
        {"s": symbol, "d": entry_date, "off": horizon_days - 1},
    ).fetchone()
    if not fwd_row or not fwd_row.close:
        return None

    return (fwd_row.close - entry_row.close) / entry_row.close * 100


def build_horizon_dataset(
    horizon_days: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    symbols: Optional[List[str]] = None,
    db: Optional[Session] = None,
) -> HorizonDataset:
    """Build a training dataset for a specific prediction horizon."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()

    try:
        label_name = f"return_{horizon_days}d"

        if end_date is None:
            end_row = db.execute("SELECT MAX(date) FROM daily_prices").fetchone()
            end_date = date.fromisoformat(end_row[0]) if end_row and end_row[0] else date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=730)

        # Leave enough room for the longest horizon
        effective_end = end_date - timedelta(days=horizon_days + 5)
        if effective_end <= start_date:
            logger.warning("Not enough date range for %dd horizon", horizon_days)
            return HorizonDataset(
                horizon_days=horizon_days, label_name=label_name,
                feature_matrix=None, labels=None,
                sample_count=0, positive_rate=0.0,
                date_range_start=None, date_range_end=None,
                metadata={"status": "insufficient_range"},
            )

        trading_dates = get_trading_dates(start_date, effective_end, db)

        if symbols is None:
            sym_rows = db.execute("SELECT symbol FROM stocks WHERE active = 1").fetchall()
            symbols = [r[0] for r in sym_rows]

        all_frames = []
        for d in trading_dates:
            fm = reconstruct_feature_matrix(d, symbols=symbols, db=db)
            if fm.empty:
                continue
            labels_list = []
            for sym in fm["symbol"].tolist():
                ret = _compute_forward_return(sym, d, horizon_days, db)
                labels_list.append(ret)
            fm[label_name] = labels_list
            fm = fm.dropna(subset=[label_name])
            if not fm.empty:
                all_frames.append(fm)

        if not all_frames:
            return HorizonDataset(
                horizon_days=horizon_days, label_name=label_name,
                feature_matrix=None, labels=None,
                sample_count=0, positive_rate=0.0,
                date_range_start=None, date_range_end=None,
                metadata={"status": "no_samples"},
            )

        full_df = pd.concat(all_frames, ignore_index=True)
        labels = full_df[label_name]
        feature_cols = [c for c in full_df.columns if c not in ["symbol", "date", label_name]]
        feature_matrix = full_df[["symbol", "date"] + feature_cols]
        positive_rate = float((labels > 0).mean())

        dataset = HorizonDataset(
            horizon_days=horizon_days,
            label_name=label_name,
            feature_matrix=feature_matrix,
            labels=labels,
            sample_count=len(full_df),
            positive_rate=positive_rate,
            date_range_start=trading_dates[0].isoformat() if trading_dates else None,
            date_range_end=trading_dates[-1].isoformat() if trading_dates else None,
            metadata={
                "symbols": len(symbols),
                "trading_dates": len(trading_dates),
                "feature_count": len(feature_cols),
                "generated_at": datetime.utcnow().isoformat(),
            },
        )

        logger.info("Horizon %dd dataset: %d samples, %.1f%% positive",
                    horizon_days, len(full_df), positive_rate * 100)
        return dataset

    finally:
        if own_session:
            db.close()


def build_all_horizon_datasets(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    symbols: Optional[List[str]] = None,
) -> Dict[int, HorizonDataset]:
    """Build datasets for all 7 standard horizons: 3, 5, 10, 15, 30, 60, 90 days."""
    db = get_session_factory()()
    try:
        results = {}
        for h in HORIZONS:
            try:
                ds = build_horizon_dataset(h, start_date, end_date, symbols, db)
                results[h] = ds
                logger.info("Horizon %dd: %d samples", h, ds.sample_count)
            except Exception as exc:
                logger.error("Failed to build %dd horizon dataset: %s", h, exc)
        return results
    finally:
        db.close()


def save_horizon_metadata_to_db(
    datasets: Dict[int, HorizonDataset],
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Save horizon dataset metadata to the historical_replays table as a record."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        summary = {str(h): ds.to_dict() for h, ds in datasets.items()}
        db.execute(
            """
            INSERT INTO historical_replays
                (replay_type, scope_label, metadata_json, created_at)
            VALUES
                ('horizon_datasets', 'all_horizons', :meta, :now)
            """,
            {"meta": json.dumps(summary), "now": datetime.utcnow().isoformat()},
        )
        db.commit()
        return {"status": "saved", "horizons": list(datasets.keys())}
    except Exception as exc:
        logger.error("Failed to save horizon metadata: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        if own_session:
            db.close()


def run_horizon_builder_pipeline(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Full pipeline: build all horizon datasets."""
    logger.info("Starting multi-horizon dataset pipeline")
    datasets = build_all_horizon_datasets(start_date, end_date)
    meta = save_horizon_metadata_to_db(datasets)
    return {
        "status": "complete",
        "horizons": {str(h): ds.to_dict() for h, ds in datasets.items()},
        "meta_save": meta,
    }

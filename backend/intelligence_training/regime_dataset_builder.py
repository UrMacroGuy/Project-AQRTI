"""
AQRTI Regime Dataset Builder — Phase 8.5B
Generates separate training universes for each market regime.
Each regime dataset is self-contained and reproducible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger
from intelligence_training.market_reconstruction import (
    reconstruct_feature_matrix, get_trading_dates,
)

logger = get_logger("regime_dataset_builder")


REGIME_DEFINITIONS = {
    "BULL_EXPANSION": {
        "regimes": ["BULL"],
        "breadth_min": 0.60,
        "vol_max": 0.20,
        "description": "Broad uptrend, >60% stocks above EMA50, low volatility",
    },
    "BULL_EXHAUSTION": {
        "regimes": ["BULL"],
        "breadth_max": 0.60,
        "vol_min": 0.18,
        "description": "Uptrend with narrowing breadth and rising vol",
    },
    "BEAR_EXPANSION": {
        "regimes": ["BEAR"],
        "breadth_max": 0.40,
        "description": "Broad downtrend, <40% stocks above EMA50",
    },
    "BEAR_CAPITULATION": {
        "regimes": ["BEAR"],
        "vol_min": 0.30,
        "description": "Extreme volatility bear — panic selling",
    },
    "RECOVERY": {
        "regimes": ["BULL", "SIDEWAYS"],
        "breadth_min": 0.45,
        "breadth_max": 0.65,
        "description": "Post-bear recovery phase",
    },
    "SECTOR_ROTATION": {
        "regimes": ["SIDEWAYS", "BULL"],
        "description": "Mixed signals, sector leadership changing",
    },
    "HIGH_VOLATILITY": {
        "regimes": ["VOLATILE", "BEAR", "BULL"],
        "vol_min": 0.25,
        "description": "Elevated volatility regardless of direction",
    },
    "LOW_VOLATILITY": {
        "regimes": ["BULL", "SIDEWAYS"],
        "vol_max": 0.12,
        "description": "Suppressed volatility, calm market",
    },
    "INSTITUTIONAL_ACCUMULATION": {
        "regimes": ["BULL", "SIDEWAYS"],
        "breadth_min": 0.55,
        "description": "Rising breadth with moderate vol — institutional buying",
    },
    "INSTITUTIONAL_DISTRIBUTION": {
        "regimes": ["BEAR", "SIDEWAYS"],
        "breadth_max": 0.45,
        "vol_min": 0.18,
        "description": "Falling breadth with rising vol — institutional selling",
    },
}


@dataclass
class RegimeDataset:
    regime_label: str
    definition: Dict[str, Any]
    dates: List[str]
    feature_matrix: Optional[pd.DataFrame]
    sample_count: int
    symbols: List[str]
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime_label": self.regime_label,
            "definition": self.definition,
            "dates": self.dates,
            "sample_count": self.sample_count,
            "symbols": self.symbols,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "metadata": self.metadata,
        }


def _date_qualifies(
    d: date,
    regime_row: Any,
    definition: Dict[str, Any],
) -> bool:
    """Check if a date matches the regime definition criteria."""
    if regime_row is None:
        return False

    # Regime name match
    if regime_row.regime not in definition.get("regimes", []):
        return False

    # Breadth filter
    breadth = regime_row.breadth_pct
    if breadth is not None:
        if "breadth_min" in definition and breadth < definition["breadth_min"]:
            return False
        if "breadth_max" in definition and breadth > definition["breadth_max"]:
            return False

    # Volatility filter
    vol = regime_row.volatility_pct
    if vol is not None:
        if "vol_min" in definition and vol < definition["vol_min"]:
            return False
        if "vol_max" in definition and vol > definition["vol_max"]:
            return False

    return True


def build_regime_dataset(
    regime_label: str,
    horizon_days: int = 5,
    db: Optional[Session] = None,
) -> RegimeDataset:
    """Build a training dataset for a specific regime label."""
    if regime_label not in REGIME_DEFINITIONS:
        raise ValueError(f"Unknown regime label: {regime_label}. "
                         f"Valid: {list(REGIME_DEFINITIONS.keys())}")

    definition = REGIME_DEFINITIONS[regime_label]
    own_session = db is None
    if own_session:
        db = get_session_factory()()

    try:
        # Get all regime records
        regime_rows = db.execute(
            "SELECT date, regime, breadth_pct, volatility_pct, confidence "
            "FROM market_regimes ORDER BY date"
        ).fetchall()

        qualifying_dates = []
        for row in regime_rows:
            d = row.date
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if _date_qualifies(d, row, definition):
                qualifying_dates.append(d)

        if not qualifying_dates:
            logger.warning("No dates qualify for regime '%s'", regime_label)
            return RegimeDataset(
                regime_label=regime_label,
                definition=definition,
                dates=[],
                feature_matrix=None,
                sample_count=0,
                symbols=[],
                date_range_start=None,
                date_range_end=None,
                metadata={"status": "no_data"},
            )

        # Build feature matrices for each qualifying date
        all_frames = []
        for d in qualifying_dates:
            fm = reconstruct_feature_matrix(d, db=db)
            if not fm.empty:
                fm["regime_label"] = regime_label
                fm["horizon_days"] = horizon_days

                # Forward label
                label_rows = db.execute(
                    "SELECT symbol, close FROM daily_prices "
                    "WHERE date > :d ORDER BY date ASC LIMIT 1",
                    {"d": d},
                ).fetchall()
                entry_rows = db.execute(
                    "SELECT symbol, close FROM daily_prices WHERE date = :d",
                    {"d": d},
                ).fetchall()

                entry_map = {r.symbol: r.close for r in entry_rows}
                label_map: Dict[str, float] = {}

                # Proper per-symbol forward label
                for sym in fm["symbol"].tolist():
                    fwd_row = db.execute(
                        "SELECT close FROM daily_prices WHERE symbol = :s AND date > :d "
                        "ORDER BY date ASC LIMIT 1 OFFSET :off",
                        {"s": sym, "d": d, "off": horizon_days - 1},
                    ).fetchone()
                    entry = entry_map.get(sym)
                    if fwd_row and entry and entry > 0:
                        label_map[sym] = (fwd_row.close - entry) / entry * 100

                fm[f"label_return_{horizon_days}d"] = fm["symbol"].map(label_map)
                all_frames.append(fm)

        if not all_frames:
            feature_matrix = pd.DataFrame()
        else:
            feature_matrix = pd.concat(all_frames, ignore_index=True)

        symbols = feature_matrix["symbol"].unique().tolist() if not feature_matrix.empty else []

        dataset = RegimeDataset(
            regime_label=regime_label,
            definition=definition,
            dates=[d.isoformat() for d in qualifying_dates],
            feature_matrix=feature_matrix,
            sample_count=len(feature_matrix),
            symbols=symbols,
            date_range_start=qualifying_dates[0].isoformat() if qualifying_dates else None,
            date_range_end=qualifying_dates[-1].isoformat() if qualifying_dates else None,
            metadata={
                "total_dates": len(qualifying_dates),
                "horizon_days": horizon_days,
                "generated_at": datetime.utcnow().isoformat(),
                "description": definition.get("description", ""),
            },
        )

        logger.info("Built regime dataset '%s': %d dates, %d samples, %d symbols",
                    regime_label, len(qualifying_dates), len(feature_matrix), len(symbols))
        return dataset

    finally:
        if own_session:
            db.close()


def build_all_regime_datasets(
    horizon_days: int = 5,
    db: Optional[Session] = None,
) -> Dict[str, RegimeDataset]:
    """Build separate datasets for all 10 regime categories."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        results = {}
        for label in REGIME_DEFINITIONS:
            try:
                dataset = build_regime_dataset(label, horizon_days, db)
                results[label] = dataset
            except Exception as exc:
                logger.error("Failed to build dataset for '%s': %s", label, exc)
        logger.info("Built %d regime datasets", len(results))
        return results
    finally:
        if own_session:
            db.close()


def save_regime_datasets_to_db(
    datasets: Dict[str, "RegimeDataset"],
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Persist regime dataset metadata to the regime_datasets table."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        saved = 0
        for label, dataset in datasets.items():
            try:
                db.execute(
                    """
                    INSERT INTO regime_datasets
                        (regime_label, definition_json, dates_json, sample_count,
                         symbols_json, date_range_start, date_range_end, metadata_json, created_at)
                    VALUES
                        (:label, :defn, :dates, :cnt, :syms, :start, :end, :meta, :now)
                    ON CONFLICT(regime_label) DO UPDATE SET
                        dates_json = excluded.dates_json,
                        sample_count = excluded.sample_count,
                        metadata_json = excluded.metadata_json,
                        created_at = excluded.created_at
                    """,
                    {
                        "label": label,
                        "defn": json.dumps(dataset.definition),
                        "dates": json.dumps(dataset.dates),
                        "cnt": dataset.sample_count,
                        "syms": json.dumps(dataset.symbols),
                        "start": dataset.date_range_start,
                        "end": dataset.date_range_end,
                        "meta": json.dumps(dataset.metadata),
                        "now": datetime.utcnow().isoformat(),
                    },
                )
                saved += 1
            except Exception as exc:
                logger.error("Failed to save dataset '%s': %s", label, exc)
        db.commit()
        return {"saved": saved, "total": len(datasets)}
    finally:
        if own_session:
            db.close()


def run_regime_dataset_pipeline(horizon_days: int = 5) -> Dict[str, Any]:
    """Full pipeline: build all regime datasets and persist metadata."""
    logger.info("Starting regime dataset pipeline (horizon=%dd)", horizon_days)
    datasets = build_all_regime_datasets(horizon_days)
    save_result = save_regime_datasets_to_db(datasets)
    summary = {}
    for label, ds in datasets.items():
        summary[label] = {
            "sample_count": ds.sample_count,
            "date_count": len(ds.dates),
            "symbols": len(ds.symbols),
        }
    return {
        "status": "complete",
        "regimes_built": len(datasets),
        "save_result": save_result,
        "summary": summary,
    }

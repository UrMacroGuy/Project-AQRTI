"""
Phase 8E — Sector Rotation Engine
Computes relative strength, RRG quadrant placement, momentum, and top stocks per sector.
Derived entirely from AQRTI's own price + sentiment data. No external scraping.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from aqrti.database.models import SectorRotation, DailyPrice, Stock, SentimentRecord

logger = logging.getLogger("data_supremacy.sector_rotation")

SECTORS = [
    "Banking", "IT", "FMCG", "Pharma", "Auto", "Metals",
    "Energy", "Realty", "Infrastructure", "Capital Goods",
    "Chemicals", "Telecom", "Media", "Consumer Durables",
]


def compute_sector_rotation(db: Session, target_date: date | None = None) -> dict:
    target = target_date or date.today()

    existing = db.query(SectorRotation).filter(
        SectorRotation.rotation_date == target
    ).count()
    if existing >= 3:
        return {"status": "already_exists", "date": str(target)}

    stocks = db.query(Stock).filter(Stock.active == True).all()
    sector_to_symbols: dict[str, list[str]] = {}
    for s in stocks:
        sec = s.sector or "Unknown"
        sector_to_symbols.setdefault(sec, []).append(s.symbol)

    # Preload Nifty returns for RS computation
    nifty_ret = _nifty_return(db, target, 20)
    nifty_ret_60 = _nifty_return(db, target, 60)

    stored = 0
    for sector, symbols in sector_to_symbols.items():
        if not symbols:
            continue

        rets = _sector_returns(db, symbols, target)
        if not rets:
            continue

        ret_1d  = rets.get("ret_1d")
        ret_5d  = rets.get("ret_5d")
        ret_20d = rets.get("ret_20d")
        ret_60d = rets.get("ret_60d")

        rs_20 = (ret_20d - nifty_ret)     if ret_20d is not None and nifty_ret is not None else None
        rs_60 = (ret_60d - nifty_ret_60)  if ret_60d is not None and nifty_ret_60 is not None else None

        # RRG quadrant: based on RS vs momentum (change in RS)
        phase = _rrg_phase(rs_20, rs_60)

        # Avg sentiment and volume ratio
        avg_sentiment    = _avg_sector_sentiment(db, symbols, target)
        avg_volume_ratio = _avg_sector_volume_ratio(db, symbols, target)

        # Top stocks by 20d return
        top_stocks = _top_stocks(db, symbols, target, n=5)

        # RS rank computed later via bulk ranking
        existing_row = db.query(SectorRotation).filter(
            SectorRotation.rotation_date == target,
            SectorRotation.sector == sector,
        ).first()

        if existing_row:
            existing_row.ret_1d           = ret_1d
            existing_row.ret_5d           = ret_5d
            existing_row.ret_20d          = ret_20d
            existing_row.ret_60d          = ret_60d
            existing_row.rs_vs_nifty_20d  = rs_20
            existing_row.rs_vs_nifty_60d  = rs_60
            existing_row.rotation_phase   = phase
            existing_row.avg_sentiment    = avg_sentiment
            existing_row.avg_volume_ratio = avg_volume_ratio
            existing_row.top_stocks_json  = json.dumps(top_stocks)
        else:
            row = SectorRotation(
                rotation_date    = target,
                sector           = sector,
                ret_1d           = ret_1d,
                ret_5d           = ret_5d,
                ret_20d          = ret_20d,
                ret_60d          = ret_60d,
                rs_vs_nifty_20d  = rs_20,
                rs_vs_nifty_60d  = rs_60,
                rotation_phase   = phase,
                avg_sentiment    = avg_sentiment,
                avg_volume_ratio = avg_volume_ratio,
                top_stocks_json  = json.dumps(top_stocks),
            )
            db.add(row)
        stored += 1

    db.flush()
    _assign_rs_ranks(db, target)
    db.commit()

    return {"status": "ok", "date": str(target), "sectors_computed": stored}


def _sector_returns(db: Session, symbols: list[str], target: date) -> dict:
    cutoff_60 = target - timedelta(days=90)
    rows = db.query(DailyPrice).filter(
        DailyPrice.symbol.in_(symbols),
        DailyPrice.date.between(cutoff_60, target),
    ).order_by(DailyPrice.date.asc()).all()

    by_symbol: dict[str, list] = {}
    for r in rows:
        by_symbol.setdefault(r.symbol, []).append(r)

    def avg_ret(n_days: int, field: str = "daily_return") -> float | None:
        vals = []
        for sym_rows in by_symbol.values():
            recent = [getattr(r, field) for r in sym_rows[-n_days:] if getattr(r, field) is not None]
            if recent:
                vals.append(sum(recent) / len(recent))
        return sum(vals) / len(vals) if vals else None

    def sector_return_nd(n_days: int) -> float | None:
        vals = []
        for sym_rows in by_symbol.values():
            recent = sym_rows[-n_days:]
            if len(recent) >= 2:
                start = recent[0].close
                end   = recent[-1].close
                if start and end and start > 0:
                    vals.append((end - start) / start * 100)
        return sum(vals) / len(vals) if vals else None

    return {
        "ret_1d":  avg_ret(1),
        "ret_5d":  sector_return_nd(5),
        "ret_20d": sector_return_nd(20),
        "ret_60d": sector_return_nd(60),
    }


def _nifty_return(db: Session, target: date, n_days: int) -> float | None:
    from aqrti.database.models import IndexData
    rows = db.query(IndexData).filter(
        IndexData.index_name == "NIFTY50",
        IndexData.date <= target,
    ).order_by(IndexData.date.desc()).limit(n_days + 5).all()
    if len(rows) < 2:
        return None
    end_close   = rows[0].close
    start_close = rows[-1].close
    if not end_close or not start_close or start_close == 0:
        return None
    return (end_close - start_close) / start_close * 100


def _rrg_phase(rs_20: float | None, rs_60: float | None) -> str:
    if rs_20 is None:
        return "UNKNOWN"
    momentum = (rs_20 - rs_60) if rs_60 is not None else 0
    if rs_20 > 0 and momentum > 0:
        return "LEADING"
    if rs_20 > 0 and momentum < 0:
        return "WEAKENING"
    if rs_20 < 0 and momentum < 0:
        return "LAGGING"
    if rs_20 < 0 and momentum > 0:
        return "IMPROVING"
    return "NEUTRAL"


def _avg_sector_sentiment(db: Session, symbols: list[str], target: date) -> float | None:
    from datetime import datetime
    cutoff = datetime.combine(target - timedelta(days=7), datetime.min.time())
    target_dt = datetime.combine(target + timedelta(days=1), datetime.min.time())
    rows = db.query(SentimentRecord).filter(
        SentimentRecord.entity.in_(symbols),
        SentimentRecord.entity_type == "stock",
        SentimentRecord.timestamp >= cutoff,
        SentimentRecord.timestamp < target_dt,
    ).all()
    scores = [r.score for r in rows if r.score is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


def _avg_sector_volume_ratio(db: Session, symbols: list[str], target: date) -> float | None:
    """Ratio of last-5d average volume to 20d average volume — >1.0 means elevated activity."""
    cutoff_20 = target - timedelta(days=30)
    rows = db.query(DailyPrice).filter(
        DailyPrice.symbol.in_(symbols),
        DailyPrice.date.between(cutoff_20, target),
        DailyPrice.volume.isnot(None),
    ).order_by(DailyPrice.date.asc()).all()
    if not rows:
        return None

    by_symbol: dict[str, list] = {}
    for r in rows:
        by_symbol.setdefault(r.symbol, []).append(r)

    ratios = []
    for sym_rows in by_symbol.values():
        if len(sym_rows) < 5:
            continue
        vol_20 = [r.volume for r in sym_rows if r.volume]
        vol_5  = [r.volume for r in sym_rows[-5:] if r.volume]
        if vol_20 and vol_5:
            avg_20 = sum(vol_20) / len(vol_20)
            avg_5  = sum(vol_5)  / len(vol_5)
            if avg_20 > 0:
                ratios.append(avg_5 / avg_20)
    return round(sum(ratios) / len(ratios), 3) if ratios else None


def _top_stocks(db: Session, symbols: list[str], target: date, n: int = 5) -> list[dict]:
    cutoff = target - timedelta(days=25)
    rows = db.query(DailyPrice).filter(
        DailyPrice.symbol.in_(symbols),
        DailyPrice.date.between(cutoff, target),
    ).all()
    by_sym: dict[str, list] = {}
    for r in rows:
        by_sym.setdefault(r.symbol, []).append(r)
    results = []
    for sym, sym_rows in by_sym.items():
        sym_rows = sorted(sym_rows, key=lambda r: r.date)
        if len(sym_rows) >= 2:
            s = sym_rows[0].close
            e = sym_rows[-1].close
            if s and e and s > 0:
                results.append({"symbol": sym, "ret_20d": round((e-s)/s*100, 2)})
    results.sort(key=lambda x: x["ret_20d"], reverse=True)
    return results[:n]


def _assign_rs_ranks(db: Session, target: date) -> None:
    rows = db.query(SectorRotation).filter(
        SectorRotation.rotation_date == target,
        SectorRotation.rs_vs_nifty_20d.isnot(None),
    ).order_by(SectorRotation.rs_vs_nifty_20d.desc()).all()
    for i, row in enumerate(rows, 1):
        row.rs_rank = i


def get_sector_rotation_latest(db: Session) -> list[dict]:
    latest_date = db.query(func.max(SectorRotation.rotation_date)).scalar()
    if not latest_date:
        return []
    rows = db.query(SectorRotation).filter(
        SectorRotation.rotation_date == latest_date
    ).order_by(SectorRotation.rs_rank.asc()).all()
    return [_to_dict(r) for r in rows]


def get_sector_history(db: Session, sector: str, days: int = 60) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(SectorRotation).filter(
        SectorRotation.sector == sector,
        SectorRotation.rotation_date >= cutoff,
    ).order_by(SectorRotation.rotation_date.asc()).all()
    return [_to_dict(r) for r in rows]


def _to_dict(r: SectorRotation) -> dict:
    try:
        top_stocks = json.loads(r.top_stocks_json) if r.top_stocks_json else []
    except Exception:
        top_stocks = []
    return {
        "rotation_date":    str(r.rotation_date),
        "sector":           r.sector,
        "ret_1d":           r.ret_1d,
        "ret_5d":           r.ret_5d,
        "ret_20d":          r.ret_20d,
        "ret_60d":          r.ret_60d,
        "rs_vs_nifty_20d":  r.rs_vs_nifty_20d,
        "rs_vs_nifty_60d":  r.rs_vs_nifty_60d,
        "rs_rank":          r.rs_rank,
        "rotation_phase":   r.rotation_phase,
        "avg_sentiment":    r.avg_sentiment,
        "avg_volume_ratio": r.avg_volume_ratio,
        "top_stocks":       top_stocks,
    }

"""
Automatic Market Regime Discovery Engine
Uses K-Means clustering on market feature vectors to discover regimes unsupervised.

Features: volatility, breadth, momentum, volume_ratio, trend_strength, advance_decline
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional
import sys, os

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    DailyPrice, IndexData, MarketBreadth,
    DiscoveredRegime, DailyRegimeAssignment, RegimeTransitionMatrix,
)
from aqrti.utils.logger import get_logger

log = get_logger("regime_discovery")

N_CLUSTERS = 6
MIN_CLUSTER_SIZE = 5
LOOKBACK_DAYS = 730
FEATURE_NAMES = ["volatility_20d", "breadth_pct", "momentum_20d", "volume_ratio", "trend_strength", "advance_decline"]
TRANSITION_PROB_FLOOR = 0.02


def _build_feature_matrix(db: Session, days: int = LOOKBACK_DAYS):
    cutoff = date.today() - timedelta(days=days)
    nifty_rows = (
        db.query(IndexData.date, IndexData.close, IndexData.returns)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff)
        .order_by(IndexData.date.asc()).all()
    )
    if len(nifty_rows) < 30:
        return [], np.array([])

    nifty_dates = [r[0] for r in nifty_rows]
    nifty_close = np.array([r[1] for r in nifty_rows], dtype=float)
    nifty_ret   = np.array([r[2] or 0.0 for r in nifty_rows], dtype=float)

    breadth_map = {}
    for br in db.query(MarketBreadth).filter(MarketBreadth.breadth_date >= cutoff).all():
        total = br.total_stocks or 500
        pct = (br.above_ma20 / total * 100) if (br.above_ma20 and total > 0) else 50.0
        breadth_map[br.breadth_date] = (pct, br.advance_decline_ratio or 1.0)

    vol_rows = db.query(DailyPrice.date, DailyPrice.volume).filter(DailyPrice.date >= cutoff).all()
    vol_by_date: dict = defaultdict(list)
    for r in vol_rows:
        if r[1]:
            vol_by_date[r[0]].append(r[1])

    rows, dates_out = [], []
    for i, d in enumerate(nifty_dates):
        if i < 20:
            continue
        window = nifty_ret[max(0, i - 20):i]
        vol_20d = float(np.std(window) * np.sqrt(252)) if len(window) > 1 else 0.15
        mom_20d = float((nifty_close[i] - nifty_close[i - 20]) / nifty_close[i - 20] * 100) if nifty_close[i - 20] > 0 else 0.0
        bpct, adr = breadth_map.get(d, (50.0, 1.0))
        today_vols = vol_by_date.get(d, [])
        past_vols = []
        for j in range(1, 21):
            if i - j >= 0:
                past_vols.extend(vol_by_date.get(nifty_dates[i - j], []))
        today_avg = float(np.mean(today_vols)) if today_vols else 1.0
        past_avg  = float(np.mean(past_vols)) if past_vols else 1.0
        vol_ratio = today_avg / past_avg if past_avg > 0 else 1.0
        trend_strength = abs(mom_20d) / (vol_20d * 100 + 1e-6)
        rows.append([vol_20d, bpct, mom_20d, vol_ratio, trend_strength, adr])
        dates_out.append(d)

    return dates_out, np.array(rows, dtype=float) if rows else np.array([])


def _normalize(X):
    means = np.nanmean(X, axis=0)
    stds  = np.nanstd(X, axis=0)
    stds[stds < 1e-8] = 1.0
    return (X - means) / stds, means, stds


def _kmeans(X, k, n_init=10, max_iter=300):
    best_labels, best_inertia, best_centroids = None, float("inf"), None
    rng = np.random.default_rng(42)
    n = len(X)
    for _ in range(n_init):
        # K-Means++ initialisation
        idx0 = int(rng.integers(n))
        centroids = [X[idx0]]
        for _ in range(k - 1):
            # Vectorised distance to nearest centroid
            C = np.array(centroids)
            d2 = np.min(np.sum((X[:, None] - C[None]) ** 2, axis=2), axis=1)
            total = d2.sum()
            if total <= 0:
                break
            probs = d2 / total
            centroids.append(X[int(rng.choice(n, p=probs))])
        if len(centroids) < k:
            # Degenerate case: duplicate points — pad with random rows
            while len(centroids) < k:
                centroids.append(X[int(rng.integers(n))])
        centroids = np.array(centroids, dtype=float)

        for _ in range(max_iter):
            # Vectorised assignment
            dists  = np.linalg.norm(X[:, None] - centroids[None], axis=2)  # (n, k)
            labels = np.argmin(dists, axis=1)
            new_c  = np.array([
                X[labels == j].mean(axis=0) if (labels == j).sum() > 0 else centroids[j]
                for j in range(k)
            ])
            if np.allclose(centroids, new_c, atol=1e-6):
                break
            centroids = new_c

        # Vectorised inertia: sum of squared distances to assigned centroid
        assigned = centroids[labels]          # (n, d)
        inertia  = float(np.sum((X - assigned) ** 2))
        if inertia < best_inertia:
            best_inertia, best_labels, best_centroids = inertia, labels.copy(), centroids.copy()

    # Safety guard: should never be None after n_init >= 1, but protect downstream
    if best_labels is None:
        best_labels    = np.zeros(n, dtype=int)
        best_centroids = np.tile(X.mean(axis=0), (k, 1))
    return best_labels, best_centroids


def _describe_regime(center):
    vol, bpct, mom = center[0], center[1], center[2]
    parts = []
    parts.append("High Vol" if vol > 0.25 else ("Low Vol" if vol < 0.12 else "Mod Vol"))
    parts.append("Strong Breadth" if bpct > 65 else ("Weak Breadth" if bpct < 35 else "Mixed Breadth"))
    parts.append("Bullish" if mom > 3 else ("Bearish" if mom < -3 else "Flat"))
    label = " / ".join(parts[:2])
    desc  = f"Vol={vol:.2f} Breadth={bpct:.1f}% Mom={mom:.1f}%"
    return label, desc


def run_regime_discovery(db: Session, n_clusters: int = N_CLUSTERS) -> dict:
    log.info("Starting regime discovery k=%d", n_clusters)
    dates, X = _build_feature_matrix(db)
    if len(dates) < n_clusters * MIN_CLUSTER_SIZE:
        return {"status": "insufficient_data", "n_dates": len(dates)}

    X_norm, means, stds = _normalize(X)
    labels, centroids = _kmeans(X_norm, n_clusters)
    centroids_raw = centroids * stds + means

    regime_stats: dict = defaultdict(lambda: {"dates": [], "vols": [], "breadths": [], "moms": [], "vrs": []})
    for i, lbl in enumerate(labels):
        regime_stats[int(lbl)]["dates"].append(dates[i])
        regime_stats[int(lbl)]["vols"].append(X[i][0])
        regime_stats[int(lbl)]["breadths"].append(X[i][1])
        regime_stats[int(lbl)]["moms"].append(X[i][2])
        regime_stats[int(lbl)]["vrs"].append(X[i][3])

    # Identify clusters below MIN_CLUSTER_SIZE; reassign their rows to the
    # nearest remaining centroid so no data is silently dropped.
    small_clusters = {
        idx for idx in range(n_clusters)
        if len(regime_stats[idx]["dates"]) < MIN_CLUSTER_SIZE
    }
    if small_clusters:
        retain = [i for i in range(n_clusters) if i not in small_clusters]
        if retain:
            centroids_retain = centroids[retain]
            for small_idx in small_clusters:
                mask = labels == small_idx
                n_small = mask.sum()
                if n_small == 0:
                    continue
                # Distance from each small-cluster row to all retained centroids
                dists = np.linalg.norm(X_norm[mask][:, None] - centroids_retain[None], axis=2)
                nearest_retain = np.argmin(dists, axis=1)
                # `retain` is a plain Python list — numpy fancy-indexing it
                # directly (retain[nearest_retain] for n_small > 1) raises
                # "only integer scalar arrays can be converted to a scalar
                # index". Index via np.array(retain) instead.
                retain_arr = np.array(retain)
                new_labels = retain[nearest_retain[0]] if n_small == 1 else retain_arr[nearest_retain]
                labels[mask] = new_labels
                # Move rows into the correct regime_stats bucket
                for orig_pos in np.where(mask)[0]:
                    orig_pos_item = int(orig_pos)
                    new_lbl_val = int(labels[orig_pos_item])
                    regime_stats[new_lbl_val]["dates"].append(dates[orig_pos_item])
                    regime_stats[new_lbl_val]["vols"].append(X[orig_pos_item][0])
                    regime_stats[new_lbl_val]["breadths"].append(X[orig_pos_item][1])
                    regime_stats[new_lbl_val]["moms"].append(X[orig_pos_item][2])
                    regime_stats[new_lbl_val]["vrs"].append(X[orig_pos_item][3])
            log.info("Reassigned %d rows from %d small clusters to nearest retained centroids",
                     sum(len(regime_stats[s]["dates"]) for s in small_clusters if s in regime_stats), len(small_clusters))

    created = updated = 0
    regime_id_map: dict[int, str] = {}

    for idx in range(n_clusters):
        stats = regime_stats[idx]
        if len(stats["dates"]) < MIN_CLUSTER_SIZE:
            continue
        rid = f"R_{idx:02d}"
        regime_id_map[idx] = rid
        label, desc = _describe_regime(centroids_raw[idx])
        centroid_dict = {fn: round(float(centroids_raw[idx][i]), 4) for i, fn in enumerate(FEATURE_NAMES)}
        ex = db.query(DiscoveredRegime).filter(DiscoveredRegime.regime_id == rid).first()
        if ex:
            ex.label = label; ex.description = desc
            ex.cluster_center_json = json.dumps(centroid_dict)
            ex.avg_volatility = float(np.mean(stats["vols"]))
            ex.avg_breadth = float(np.mean(stats["breadths"]))
            ex.avg_momentum = float(np.mean(stats["moms"]))
            ex.avg_volume_ratio = float(np.mean(stats["vrs"]))
            ex.sample_count = len(stats["dates"])
            ex.first_seen = min(stats["dates"]); ex.last_seen = max(stats["dates"])
            updated += 1
        else:
            db.add(DiscoveredRegime(
                regime_id=rid, label=label, description=desc,
                cluster_center_json=json.dumps(centroid_dict),
                feature_names_json=json.dumps(FEATURE_NAMES),
                avg_volatility=float(np.mean(stats["vols"])),
                avg_breadth=float(np.mean(stats["breadths"])),
                avg_momentum=float(np.mean(stats["moms"])),
                avg_volume_ratio=float(np.mean(stats["vrs"])),
                sample_count=len(stats["dates"]),
                first_seen=min(stats["dates"]), last_seen=max(stats["dates"]),
            ))
            created += 1
    db.commit()

    dists_all = np.linalg.norm(X_norm[:, None] - centroids[None], axis=2)
    inv_dists  = 1.0 / (dists_all + 1e-8)
    conf_scores = inv_dists[np.arange(len(labels)), labels] / inv_dists.sum(axis=1)

    written = 0
    for i, (d, lbl) in enumerate(zip(dates, labels)):
        rid = regime_id_map.get(int(lbl))
        if not rid:
            continue
        ex = db.query(DailyRegimeAssignment).filter(DailyRegimeAssignment.date == d).first()
        feat_vec = {fn: round(float(X[i][j]), 4) for j, fn in enumerate(FEATURE_NAMES)}
        conf = float(conf_scores[i])
        dist = float(dists_all[i][lbl])
        if ex:
            ex.regime_id = rid; ex.confidence = conf
            ex.feature_vector_json = json.dumps(feat_vec); ex.nearest_centroid_dist = dist
        else:
            db.add(DailyRegimeAssignment(
                date=d, regime_id=rid, confidence=conf,
                feature_vector_json=json.dumps(feat_vec), nearest_centroid_dist=dist,
            ))
        written += 1
    db.commit()

    # Transition matrix
    tc: dict[tuple, int] = defaultdict(int)
    tf: dict[str, int]   = defaultdict(int)
    for i in range(len(labels) - 1):
        fr = regime_id_map.get(int(labels[i]))
        to = regime_id_map.get(int(labels[i + 1]))
        if fr and to:
            tc[(fr, to)] += 1; tf[fr] += 1
    for (fr, to), cnt in tc.items():
        prob = cnt / tf[fr] if tf[fr] > 0 else 0.0
        if prob < TRANSITION_PROB_FLOOR:
            continue
        ex = db.query(RegimeTransitionMatrix).filter(
            RegimeTransitionMatrix.from_regime == fr, RegimeTransitionMatrix.to_regime == to
        ).first()
        if ex:
            ex.transition_count = cnt; ex.transition_probability = prob
        else:
            db.add(RegimeTransitionMatrix(from_regime=fr, to_regime=to, transition_count=cnt, transition_probability=prob))
    db.commit()

    log.info("Regime discovery: created=%d updated=%d assignments=%d", created, updated, written)
    return {"status": "ok", "n_regimes": len(regime_id_map), "n_dates": len(dates),
            "created": created, "updated": updated, "assignments_written": written}


def get_todays_regime(db: Session) -> Optional[dict]:
    row = db.query(DailyRegimeAssignment).order_by(DailyRegimeAssignment.date.desc()).first()
    if not row:
        return None
    regime = db.query(DiscoveredRegime).filter(DiscoveredRegime.regime_id == row.regime_id).first()
    return {
        "date": str(row.date), "regime_id": row.regime_id,
        "label": regime.label if regime else row.regime_id,
        "description": regime.description if regime else "",
        "confidence": row.confidence,
        "feature_vector": json.loads(row.feature_vector_json or "{}"),
    }


def get_regime_history(db: Session, days: int = 90) -> list:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(DailyRegimeAssignment).filter(DailyRegimeAssignment.date >= cutoff).order_by(DailyRegimeAssignment.date.asc()).all()
    regimes = {r.regime_id: r for r in db.query(DiscoveredRegime).all()}
    return [{"date": str(r.date), "regime_id": r.regime_id,
             "label": regimes[r.regime_id].label if r.regime_id in regimes else r.regime_id,
             "confidence": r.confidence} for r in rows]


def get_regime_stats(db: Session) -> list:
    rows = db.query(DiscoveredRegime).filter(DiscoveredRegime.is_active == True).all()
    return [{"regime_id": r.regime_id, "label": r.label, "description": r.description,
             "avg_volatility": r.avg_volatility, "avg_breadth": r.avg_breadth,
             "avg_momentum": r.avg_momentum, "sample_count": r.sample_count,
             "centroid": json.loads(r.cluster_center_json or "{}")} for r in rows]

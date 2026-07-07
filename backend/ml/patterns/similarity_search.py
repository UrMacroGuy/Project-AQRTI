"""
AQRTI Similarity Search
Finds historical feature vectors most similar to the current one.

Method: cosine similarity on normalized feature vectors.
Euclidean distance used as secondary tie-breaker.

All historical vectors are loaded from the feature_values table.
No external index library required — pure NumPy.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from scipy.spatial.distance import cosine as cosine_distance

from aqrti.utils.logger import get_logger

log = get_logger("similarity_search")

# Maximum number of similar situations to return
TOP_K = 10

# Minimum data points for a historical vector to be considered
MIN_FEATURE_COVERAGE = 0.60    # at least 60% of features must be non-NaN


def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize a vector. Returns zero vector if norm is zero."""
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [−1, 1]."""
    a_n = _normalize(a)
    b_n = _normalize(b)
    return float(np.dot(a_n, b_n))


def build_historical_matrix(
    db,
    feature_cols: list[str],
    symbol: Optional[str] = None,
    days: int = 1200,
    version: int = 1,
) -> tuple[np.ndarray, list[tuple[str, date]]]:
    """
    Load historical feature vectors from DB into a matrix.

    Args:
        db:           SQLAlchemy session
        feature_cols: Ordered list of feature names
        symbol:       If given, only load vectors for this symbol
        days:         How far back to look
        version:      Feature version

    Returns:
        matrix: shape (N, len(feature_cols)), float64
        index:  list of (symbol, date) matching each row
    """
    from aqrti.database.models import FeatureValue

    cutoff = date.today() - timedelta(days=days)
    q = (
        db.query(FeatureValue.symbol, FeatureValue.date,
                 FeatureValue.feature_name, FeatureValue.value)
        .filter(
            FeatureValue.version      == version,
            FeatureValue.feature_name.in_(feature_cols),
            FeatureValue.date         >= cutoff,
        )
    )
    if symbol:
        q = q.filter(FeatureValue.symbol == symbol)

    rows = q.all()
    if not rows:
        return np.array([]), []

    # Pivot: (symbol, date) → feature_name → value
    records = {}
    for r in rows:
        key = (r.symbol, r.date)
        if key not in records:
            records[key] = {}
        records[key][r.feature_name] = r.value

    # Filter by minimum coverage and build matrix
    feat_idx = {f: i for i, f in enumerate(feature_cols)}
    matrix_rows = []
    index       = []

    for (sym, dt), feat_map in records.items():
        coverage = len(feat_map) / max(len(feature_cols), 1)
        if coverage < MIN_FEATURE_COVERAGE:
            continue

        vec = np.zeros(len(feature_cols), dtype=np.float64)
        for fname, fval in feat_map.items():
            if fname in feat_idx and fval is not None:
                vec[feat_idx[fname]] = float(fval)

        matrix_rows.append(vec)
        index.append((sym, dt))

    if not matrix_rows:
        return np.array([]), []

    matrix = np.vstack(matrix_rows)
    return matrix, index


def find_similar_situations(
    current_features: dict[str, float],
    feature_cols: list[str],
    db,
    symbol: Optional[str] = None,
    top_k: int = TOP_K,
    days: int = 1200,
    version: int = 1,
    exclude_same_symbol: bool = False,
    prebuilt_matrix: Optional[tuple[np.ndarray, list[tuple[str, date]]]] = None,
) -> list[dict]:
    """
    Find top_k historical situations most similar to current_features.

    Args:
        current_features:     {feature_name: value} for the current observation
        feature_cols:         Ordered feature list (must match training)
        db:                   SQLAlchemy session
        symbol:               Current symbol (for excluding it from results)
        top_k:                Number of similar situations to return
        days:                 Historical lookback window
        exclude_same_symbol:  If True, only return matches from OTHER symbols
        prebuilt_matrix:      Optional (matrix, index) tuple from a prior
                               build_historical_matrix() call. The historical
                               matrix is identical across every symbol within
                               one prediction run (it searches the whole
                               market, not just `symbol`'s own history), so
                               callers doing many searches in one run (e.g.
                               prediction_pipeline.py looping every symbol)
                               should build it once and pass it here instead
                               of re-querying+re-pivoting the full universe's
                               feature history on every call.

    Returns:
        List of dicts: {symbol, date, similarity_score, rank}
    """
    # Build current vector
    current_vec = np.zeros(len(feature_cols), dtype=np.float64)
    feat_idx = {f: i for i, f in enumerate(feature_cols)}
    for fname, fval in current_features.items():
        if fname in feat_idx and fval is not None and not np.isnan(fval):
            current_vec[feat_idx[fname]] = float(fval)

    if prebuilt_matrix is not None:
        matrix, index = prebuilt_matrix
    else:
        matrix, index = build_historical_matrix(db, feature_cols, days=days, version=version)

    if matrix.size == 0:
        log.warning("No historical vectors found for similarity search")
        return []

    # Compute cosine similarities (vectorized)
    current_norm = _normalize(current_vec)
    matrix_norms = np.apply_along_axis(_normalize, 1, matrix)
    similarities = matrix_norms @ current_norm   # dot product of normalized vectors = cosine sim

    # Get top-k indices (descending similarity)
    if exclude_same_symbol and symbol:
        # Mask out same symbol
        mask = np.array([s != symbol for s, _ in index], dtype=bool)
        masked_sims = np.where(mask, similarities, -2.0)
        top_indices = np.argsort(masked_sims)[::-1][:top_k]
    else:
        # Exclude today's exact match (same symbol, same or future date)
        today = date.today()
        mask = np.array(
            [not (s == symbol and d >= today) for s, d in index],
            dtype=bool,
        )
        masked_sims = np.where(mask, similarities, -2.0)
        top_indices = np.argsort(masked_sims)[::-1][:top_k]

    results = []
    for rank, idx in enumerate(top_indices, start=1):
        sim_score = float(similarities[idx])
        if sim_score < 0:   # ignore negative similarity (opposite direction)
            continue
        sym, dt = index[idx]
        results.append({
            "symbol":           sym,
            "date":             str(dt),
            "similarity_score": round(sim_score, 4),
            "rank":             rank,
        })

    return results

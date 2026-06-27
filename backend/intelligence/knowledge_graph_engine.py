"""
Knowledge Graph Engine — builds semantic graph of strategies, features, regimes, failures, lessons.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    KnowledgeNode, KnowledgeEdge, StrategyV2, FailureRecord,
    FeatureDecayHistory, StrategyDNA, MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("knowledge_graph")


def _upsert_node(db, node_type, node_key, label, props=None, inc=1):
    node = db.query(KnowledgeNode).filter(
        KnowledgeNode.node_type == node_type, KnowledgeNode.node_key == node_key).first()
    if node:
        node.label = label; node.evidence_count += inc
        if props:
            ep = json.loads(node.properties_json or "{}")
            ep.update(props); node.properties_json = json.dumps(ep)
    else:
        node = KnowledgeNode(node_type=node_type, node_key=node_key, label=label,
                             properties_json=json.dumps(props or {}), evidence_count=inc)
        db.add(node)
    db.flush()
    return node


def _upsert_edge(db, from_id, to_id, edge_type, weight_delta=0.1, evidence=None):
    edge = db.query(KnowledgeEdge).filter(
        KnowledgeEdge.from_node_id == from_id, KnowledgeEdge.to_node_id == to_id,
        KnowledgeEdge.edge_type == edge_type).first()
    if edge:
        edge.weight = min(10.0, edge.weight + weight_delta); edge.evidence_count += 1
        if evidence:
            ev = json.loads(edge.evidence_json or "{}"); ev.update(evidence)
            edge.evidence_json = json.dumps(ev)
    else:
        db.add(KnowledgeEdge(from_node_id=from_id, to_node_id=to_id, edge_type=edge_type,
                             weight=1.0, evidence_json=json.dumps(evidence or {})))


def update_graph_from_strategies(db: Session):
    strategies = db.query(StrategyV2).filter(
        StrategyV2.status.in_(["promoted", "active", "shadow"])).limit(500).all()
    regimes = db.query(MarketRegime).all()
    regime_nodes = {}
    for r in regimes:
        rn = _upsert_node(db, "regime", r.regime, f"Regime: {r.regime}")
        regime_nodes[r.regime] = rn

    for s in strategies:
        sn = _upsert_node(db, "strategy", s.strategy_id,
                          f"{s.name or s.strategy_id} [{s.family}]",
                          {"family": s.family, "fitness": s.fitness_score, "status": s.status})
        dna = db.query(StrategyDNA).filter(StrategyDNA.strategy_id == s.strategy_id).first()
        if dna:
            for feat in json.loads(dna.indicator_set_json or "[]"):
                fn = _upsert_node(db, "feature", feat, f"Feature: {feat}")
                _upsert_edge(db, sn.id, fn.id, "uses_feature", evidence={"fitness": s.fitness_score})
        allowed = json.loads(s.dsl_json or "{}").get("allowed_regimes") or []
        for reg in allowed:
            if reg in regime_nodes:
                _upsert_edge(db, sn.id, regime_nodes[reg].id, "works_in",
                             evidence={"status": s.status})
    log.info("Graph: updated %d strategies", len(strategies))


def update_graph_from_failures(db: Session, days: int = 30):
    cutoff = date.today() - timedelta(days=days)
    failures = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).all()
    for f in failures:
        fn = _upsert_node(db, "failure", f"{f.failure_category}:{f.symbol}:{f.failure_date}",
                          f"Failure: {f.failure_category} on {f.symbol}",
                          {"severity": f.severity, "regime": f.regime_at})
        if f.regime_at:
            rn = _upsert_node(db, "regime", f.regime_at, f"Regime: {f.regime_at}")
            _upsert_edge(db, rn.id, fn.id, "contributes_to",
                         evidence={"failure_type": f.failure_category})
    log.info("Graph: updated from %d failures", len(failures))


def update_graph_from_feature_decay(db: Session):
    decaying = db.query(FeatureDecayHistory).filter(FeatureDecayHistory.decay_flag == True).limit(100).all()
    for fd in decaying:
        fn = _upsert_node(db, "feature", fd.feature_name, f"Feature: {fd.feature_name}")
        sn = _upsert_node(db, "signal_quality", "prediction_accuracy", "Prediction Accuracy")
        _upsert_edge(db, fn.id, sn.id, "degrades",
                     evidence={"ic_30d": fd.ic_30d, "severity": fd.decay_severity})


def run_full_graph_update(db: Session) -> dict:
    log.info("Running full knowledge graph update")
    update_graph_from_strategies(db)
    update_graph_from_failures(db)
    update_graph_from_feature_decay(db)
    db.commit()  # single commit for all three phases
    nodes = db.query(KnowledgeNode).count()
    edges = db.query(KnowledgeEdge).count()
    log.info("Graph: %d nodes, %d edges", nodes, edges)
    return {"status": "ok", "nodes": nodes, "edges": edges}


def query_graph(db: Session, question: str) -> dict:
    q = question.lower()
    if "works in" in q:
        regime_key = q.split("works in")[-1].strip().upper()
        rn = db.query(KnowledgeNode).filter(
            KnowledgeNode.node_type == "regime", KnowledgeNode.node_key == regime_key).first()
        if not rn:
            return {"answer": f"No data for regime {regime_key}", "results": []}
        edges = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.to_node_id == rn.id, KnowledgeEdge.edge_type == "works_in"
        ).order_by(KnowledgeEdge.weight.desc()).limit(10).all()
        results = []
        for e in edges:
            n = db.query(KnowledgeNode).filter(KnowledgeNode.id == e.from_node_id).first()
            if n: results.append({"node": n.label, "weight": e.weight, "type": n.node_type})
        return {"answer": f"Things that work in {regime_key}", "results": results}
    if "uses" in q or "feature" in q:
        feat_part = q.split("uses")[-1].strip() if "uses" in q else q
        feat_nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.node_type == "feature", KnowledgeNode.node_key.ilike(f"%{feat_part}%")).limit(3).all()
        results = []
        for fn in feat_nodes:
            edges = db.query(KnowledgeEdge).filter(
                KnowledgeEdge.to_node_id == fn.id, KnowledgeEdge.edge_type == "uses_feature"
            ).order_by(KnowledgeEdge.weight.desc()).limit(5).all()
            for e in edges:
                n = db.query(KnowledgeNode).filter(KnowledgeNode.id == e.from_node_id).first()
                if n: results.append({"strategy": n.label, "feature": fn.label, "weight": e.weight})
        return {"answer": f"Strategies using '{feat_part}'", "results": results}
    return {"answer": "Try: 'what works in BULL' or 'what uses rsi_14'", "results": []}


def get_graph_summary(db: Session) -> dict:
    nodes = db.query(KnowledgeNode).count()
    edges = db.query(KnowledgeEdge).count()
    nbt = {row[0]: db.query(KnowledgeNode).filter(KnowledgeNode.node_type == row[0]).count()
           for row in db.query(KnowledgeNode.node_type).distinct()}
    ebt = {row[0]: db.query(KnowledgeEdge).filter(KnowledgeEdge.edge_type == row[0]).count()
           for row in db.query(KnowledgeEdge.edge_type).distinct()}
    return {"total_nodes": nodes, "total_edges": edges, "nodes_by_type": nbt, "edges_by_type": ebt}

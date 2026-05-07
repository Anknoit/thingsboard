"""
gnn.py — GNN root cause analysis service.

Uses a 2-layer Graph Convolutional Network (GCN) trained on historical cascade
events to identify the root-cause node in a multi-device alarm cascade.

Architecture:
  Node features (5-dim per node):
    [0] device_class_idx  — integer index (0–6) for device_class embedding
    [1] alarm_count_norm  — normalised recent alarm count (0–1)
    [2] anomaly_score_norm — normalised anomaly score (0–1)
    [3] is_in_cascade      — 1 if device is in the current cascade, else 0
    [4] cascade_position   — position in cascade (0 = first, normalised)

  GCN:
    GCNConv(5, 32) → ReLU → Dropout(0.3) → GCNConv(32, 16) → Linear(16, 1) → Sigmoid

  Output: root_cause probability per node (highest = root cause)

Training data: built from AuditLog entries of type 'alarm_cascade_analyzed'
that store the entity_ids involved + confirmed root cause (manual feedback or
heuristic label from first-alarm ordering).

If the model is not trained or PyTorch Geometric is unavailable, the service
falls back to a topology-aware heuristic:
  1. Find node with highest in-degree in the cascade subgraph (upstream = root).
  2. If tied, pick the first device in alarm time order.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import torch
import torch.nn as nn
import numpy as np

from config import settings
from models.schemas import RootCauseResult
from services.topology import get_topology

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "gnn_rootcause.pth")

# Device class → integer index for node features
DEVICE_CLASS_IDX: dict[str, int] = {
    "hvac":       0,
    "energy":     1,
    "network":    2,
    "infra":      3,
    "occupancy":  4,
    "elevator":   5,
    "fire":       6,
}

NODE_FEATURES = 5   # see module docstring
GCN_HIDDEN1   = 32
GCN_HIDDEN2   = 16


# ── PyTorch Geometric model (optional dependency) ─────────────────────────────

def _pyg_available() -> bool:
    try:
        import torch_geometric  # noqa: F401
        return True
    except ImportError:
        return False


class _GCNModel(nn.Module):
    """2-layer GCN with sigmoid output for root-cause probability."""

    def __init__(self) -> None:
        super().__init__()
        try:
            from torch_geometric.nn import GCNConv
            self._use_pyg = True
            self.conv1 = GCNConv(NODE_FEATURES, GCN_HIDDEN1)
            self.conv2 = GCNConv(GCN_HIDDEN1, GCN_HIDDEN2)
        except ImportError:
            self._use_pyg = False
            # Fallback: plain linear layers (no message passing)
            self.conv1 = nn.Linear(NODE_FEATURES, GCN_HIDDEN1)
            self.conv2 = nn.Linear(GCN_HIDDEN1, GCN_HIDDEN2)

        self.dropout = nn.Dropout(0.3)
        self.fc      = nn.Linear(GCN_HIDDEN2, 1)
        self.sigmoid = nn.Sigmoid()
        self.relu    = nn.ReLU()

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
    ) -> torch.Tensor:
        if self._use_pyg:
            out = self.relu(self.conv1(x, edge_index))
            out = self.dropout(out)
            out = self.relu(self.conv2(out, edge_index))
        else:
            out = self.relu(self.conv1(x))
            out = self.dropout(out)
            out = self.relu(self.conv2(out))
        return self.sigmoid(self.fc(out))   # (N, 1)


# ── Main service ──────────────────────────────────────────────────────────────

class GNNRootCauseService:
    def __init__(self) -> None:
        self._model: _GCNModel | None = None
        self._model_loaded = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def find_root_cause(
        self,
        entity_ids: list[str],
        anomaly_scores: dict[str, float] | None = None,
        alarm_counts: dict[str, int] | None = None,
    ) -> RootCauseResult:
        """
        Identify root cause from a cascade of entity_ids.

        Args:
            entity_ids:    list of device IDs involved in the cascade,
                           in alarm-time order (earliest first).
            anomaly_scores: optional map of entity_id → score (0–100)
            alarm_counts:   optional map of entity_id → recent alarm count
        """
        t0 = time.monotonic()

        anomaly_scores = anomaly_scores or {}
        alarm_counts   = alarm_counts   or {}

        model = self._load_model()
        if model is not None:
            try:
                result = self._gnn_inference(
                    model, entity_ids, anomaly_scores, alarm_counts
                )
            except Exception as exc:
                logger.warning("GNN inference failed (%s) — using heuristic", exc)
                result = self._heuristic(entity_ids, anomaly_scores, alarm_counts)
        else:
            logger.info("GNN model not found — using heuristic fallback")
            result = self._heuristic(entity_ids, anomaly_scores, alarm_counts)

        result.duration_ms = int((time.monotonic() - t0) * 1000)
        return result

    async def train_from_audit_log(self, lookback_days: int = 30, epochs: int = 50) -> dict:
        """
        Train the GCN from AuditLog entries of type 'alarm_cascade_analyzed'.
        Returns a summary dict. Designed to be called from a scheduler or debug endpoint.
        """
        from db.postgres import AsyncSessionLocal, AuditLog
        from sqlalchemy import select

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.event_type == "alarm_cascade_analyzed")
                    .where(AuditLog.created_at >= cutoff)
                )
            ).scalars().all()

        if not rows:
            logger.info("GNN train: no cascade audit log entries found")
            return {"status": "no_data", "samples": 0}

        samples = []
        for row in rows:
            payload = row.payload or {}
            entity_ids = payload.get("entity_ids", [])
            root_cause = payload.get("root_cause_entity_id")
            if entity_ids and root_cause and root_cause in entity_ids:
                samples.append({
                    "entity_ids": entity_ids,
                    "root_cause": root_cause,
                    "anomaly_scores": payload.get("anomaly_scores", {}),
                    "alarm_counts":   payload.get("alarm_counts", {}),
                })

        if len(samples) < 5:
            logger.info("GNN train: insufficient samples (%d < 5)", len(samples))
            return {"status": "insufficient_data", "samples": len(samples)}

        logger.info("GNN train: training on %d cascade samples", len(samples))
        return await asyncio.get_event_loop().run_in_executor(
            None, self._train_sync, samples, epochs
        )

    # ── GNN inference ──────────────────────────────────────────────────────────

    def _gnn_inference(
        self,
        model: _GCNModel,
        entity_ids: list[str],
        anomaly_scores: dict[str, float],
        alarm_counts: dict[str, int],
    ) -> RootCauseResult:
        topo     = get_topology()
        subgraph = topo.get_subgraph(entity_ids, hops=2)

        # All nodes in subgraph, with cascade nodes first
        all_nodes: list[str] = list(entity_ids) + [
            n for n in subgraph.nodes if n not in entity_ids
        ]
        node_index: dict[str, int] = {n: i for i, n in enumerate(all_nodes)}

        # Build node feature matrix
        x = self._build_node_features(
            all_nodes, entity_ids, subgraph, anomaly_scores, alarm_counts
        )

        # Build edge index from subgraph
        edge_index = self._build_edge_index(subgraph, node_index)

        model.eval()
        with torch.no_grad():
            probs = model(x, edge_index).squeeze(1)  # (N,)

        # Only consider nodes that are part of the cascade
        cascade_mask = torch.zeros(len(all_nodes), dtype=torch.bool)
        for eid in entity_ids:
            if eid in node_index:
                cascade_mask[node_index[eid]] = True

        cascade_probs = probs.clone()
        cascade_probs[~cascade_mask] = -1.0
        root_idx = int(cascade_probs.argmax().item())
        root_id  = all_nodes[root_idx]
        root_prob = float(probs[root_idx].item())

        node_attrs = topo.node_attrs(root_id)
        blast_radius = self._compute_blast_radius(root_id, entity_ids, subgraph)
        explanation  = self._explain(root_id, root_prob, node_attrs, blast_radius)

        return RootCauseResult(
            root_cause_entity_id=root_id,
            root_cause_device_name=node_attrs.get("device_name", root_id),
            confidence=round(root_prob, 3),
            explanation=explanation,
            blast_radius=blast_radius,
            duration_ms=0,
        )

    def _build_node_features(
        self,
        all_nodes: list[str],
        cascade_ids: list[str],
        subgraph,
        anomaly_scores: dict[str, float],
        alarm_counts: dict[str, int],
    ) -> torch.Tensor:
        topo    = get_topology()
        cascade_set = set(cascade_ids)
        max_alarms  = max(alarm_counts.values(), default=1) or 1
        n_cascade   = len(cascade_ids)

        rows = []
        for node in all_nodes:
            attrs      = topo.node_attrs(node)
            dc_idx     = DEVICE_CLASS_IDX.get(attrs.get("device_class", ""), 3) / 6.0
            alarm_norm = alarm_counts.get(node, 0) / max_alarms
            score_norm = anomaly_scores.get(node, 0.0) / 100.0
            in_cascade = 1.0 if node in cascade_set else 0.0
            cascade_pos = (
                cascade_ids.index(node) / n_cascade
                if node in cascade_ids else 0.0
            )
            rows.append([dc_idx, alarm_norm, score_norm, in_cascade, cascade_pos])

        return torch.tensor(rows, dtype=torch.float32)

    def _build_edge_index(
        self,
        subgraph,
        node_index: dict[str, int],
    ) -> torch.Tensor:
        src, dst = [], []
        for u, v in subgraph.edges():
            if u in node_index and v in node_index:
                src.append(node_index[u])
                dst.append(node_index[v])
                # Add reverse edge for undirected message passing
                src.append(node_index[v])
                dst.append(node_index[u])

        if not src:
            # Self-loops only (degenerate graph)
            n = len(node_index)
            idx = list(range(n))
            return torch.tensor([idx, idx], dtype=torch.long)

        return torch.tensor([src, dst], dtype=torch.long)

    # ── Heuristic fallback ─────────────────────────────────────────────────────

    def _heuristic(
        self,
        entity_ids: list[str],
        anomaly_scores: dict[str, float],
        alarm_counts: dict[str, int],
    ) -> RootCauseResult:
        """
        Topology-aware heuristic:
          1. Build subgraph and count in-degree (upstream devices = higher in-degree).
          2. Among cascade nodes, pick highest in-degree.
          3. Break ties by earliest cascade position + highest anomaly score.
        """
        topo     = get_topology()
        subgraph = topo.get_subgraph(entity_ids, hops=2)

        in_degrees: dict[str, int] = {
            n: subgraph.in_degree(n)
            for n in entity_ids
            if n in subgraph
        }

        if not in_degrees:
            # No topology info — fall back to first device + anomaly score
            best = max(
                entity_ids,
                key=lambda e: anomaly_scores.get(e, 0.0),
                default=entity_ids[0],
            )
            confidence = 0.40
        else:
            max_in = max(in_degrees.values())
            candidates = [
                n for n, d in in_degrees.items() if d == max_in
            ]
            # Tie-break: highest anomaly score, then earliest position
            best = min(
                candidates,
                key=lambda n: (
                    -anomaly_scores.get(n, 0.0),
                    entity_ids.index(n) if n in entity_ids else 999,
                ),
            )
            confidence = min(0.75, 0.40 + 0.05 * max_in)

        node_attrs    = topo.node_attrs(best)
        blast_radius  = self._compute_blast_radius(best, entity_ids, subgraph)
        explanation   = self._explain(best, confidence, node_attrs, blast_radius, heuristic=True)

        return RootCauseResult(
            root_cause_entity_id=best,
            root_cause_device_name=node_attrs.get("device_name", best),
            confidence=round(confidence, 3),
            explanation=explanation,
            blast_radius=blast_radius,
            duration_ms=0,
        )

    # ── Training ───────────────────────────────────────────────────────────────

    def _train_sync(self, samples: list[dict], epochs: int) -> dict:
        """CPU-bound training — call via run_in_executor."""
        model = _GCNModel()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        model.train()
        total_loss = 0.0
        n_batches  = 0

        for epoch in range(epochs):
            epoch_loss = 0.0
            for sample in samples:
                entity_ids    = sample["entity_ids"]
                root_cause    = sample["root_cause"]
                anomaly_scores = sample.get("anomaly_scores", {})
                alarm_counts   = sample.get("alarm_counts", {})

                topo     = get_topology()
                subgraph = topo.get_subgraph(entity_ids, hops=2)

                all_nodes  = list(entity_ids) + [
                    n for n in subgraph.nodes if n not in entity_ids
                ]
                node_index = {n: i for i, n in enumerate(all_nodes)}

                x          = self._build_node_features(
                    all_nodes, entity_ids, subgraph, anomaly_scores, alarm_counts
                )
                edge_index = self._build_edge_index(subgraph, node_index)

                # Labels: 1.0 for root cause, 0.0 for others
                y = torch.zeros(len(all_nodes), 1, dtype=torch.float32)
                if root_cause in node_index:
                    y[node_index[root_cause]] = 1.0

                optimizer.zero_grad()
                probs = model(x, edge_index)
                loss  = criterion(probs, y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
                n_batches  += 1

            if (epoch + 1) % 10 == 0:
                logger.info(
                    "GNN train: epoch %d/%d avg_loss=%.4f",
                    epoch + 1, epochs, epoch_loss / max(len(samples), 1)
                )

        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        torch.save(model.state_dict(), MODEL_PATH)
        model.eval()
        self._model = model
        self._model_loaded = True

        logger.info("GNN model saved: %s", MODEL_PATH)
        return {
            "status": "trained",
            "samples": len(samples),
            "epochs": epochs,
            "final_loss": round(epoch_loss / max(len(samples), 1), 5),
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _load_model(self) -> _GCNModel | None:
        if self._model_loaded:
            return self._model

        if not os.path.exists(MODEL_PATH):
            self._model_loaded = True
            return None

        try:
            m = _GCNModel()
            m.load_state_dict(
                torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
            )
            m.eval()
            self._model = m
            self._model_loaded = True
            logger.info("GNN model loaded from %s", MODEL_PATH)
            return m
        except Exception as exc:
            logger.error("GNN model load failed: %s", exc)
            self._model_loaded = True
            return None

    def _compute_blast_radius(
        self,
        root_id: str,
        cascade_ids: list[str],
        subgraph,
    ) -> list[str]:
        """
        Return ordered blast radius: root first, then downstream nodes reachable
        from root in the subgraph, then remaining cascade nodes.
        """
        downstream: list[str] = []
        try:
            downstream = list(nx_descendants(subgraph, root_id))
        except Exception:
            pass

        ordered = [root_id]
        for n in cascade_ids:
            if n != root_id and n not in ordered:
                ordered.append(n)
        for n in downstream:
            if n not in ordered:
                ordered.append(n)
        return ordered

    def _explain(
        self,
        root_id: str,
        confidence: float,
        node_attrs: dict,
        blast_radius: list[str],
        heuristic: bool = False,
    ) -> str:
        method   = "heuristic topology analysis" if heuristic else "GNN inference"
        dc       = node_attrs.get("device_class", "unknown").upper()
        name     = node_attrs.get("device_name", root_id)
        n_impact = len(blast_radius) - 1
        conf_pct = int(confidence * 100)

        return (
            f"{method.capitalize()} identified {name} ({dc}) as the root cause "
            f"with {conf_pct}% confidence. "
            f"This device's failure pattern propagated to {n_impact} downstream "
            f"device(s). Recommended action: inspect {name} first before "
            f"investigating dependent systems."
        )


# ── NetworkX helper (avoids nx import at module level for testability) ────────

def nx_descendants(g, node: str) -> list[str]:
    import networkx as nx
    try:
        return list(nx.descendants(g, node))
    except nx.NetworkXError:
        return []


# ── Module-level singleton ────────────────────────────────────────────────────

_service: GNNRootCauseService | None = None


def get_gnn_service() -> GNNRootCauseService:
    global _service
    if _service is None:
        _service = GNNRootCauseService()
    return _service

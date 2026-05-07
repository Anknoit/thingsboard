"""
GNN root-cause analysis — stub.
Full implementation in Phase 7.
Falls back to heuristic: device with most recent alarm is root cause.
"""

import logging
import os
import time
from datetime import datetime, timezone

from models.schemas import RootCauseResult
from services.topology import TopologyGraph

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "gnn_rootcause.pth")

_topology = TopologyGraph()


class GNNRootCauseService:
    def find_root_cause(self, entity_ids: list[str]) -> RootCauseResult:
        t0 = time.monotonic()

        if os.path.exists(MODEL_PATH):
            result = self._gnn_inference(entity_ids)
        else:
            logger.info("GNN model not found — using heuristic fallback")
            result = self._heuristic(entity_ids)

        result.duration_ms = int((time.monotonic() - t0) * 1000)
        return result

    def _heuristic(self, entity_ids: list[str]) -> RootCauseResult:
        """
        Heuristic: first entity in the cascade list is the root cause.
        Phase 7 replaces with real GNN inference.
        """
        root_id = entity_ids[0] if entity_ids else "unknown"
        return RootCauseResult(
            root_cause_entity_id=root_id,
            root_cause_device_name=root_id,
            confidence=0.5,
            explanation=(
                f"Heuristic analysis identified {root_id} as the likely root cause "
                f"based on alarm ordering across {len(entity_ids)} affected devices. "
                "GNN model not yet trained."
            ),
            blast_radius=entity_ids,
            duration_ms=0,
        )

    def _gnn_inference(self, entity_ids: list[str]) -> RootCauseResult:
        """Phase 7: full PyTorch Geometric GCN inference."""
        raise NotImplementedError("GNN inference implemented in Phase 7")


_service: GNNRootCauseService | None = None


def get_gnn_service() -> GNNRootCauseService:
    global _service
    if _service is None:
        _service = GNNRootCauseService()
    return _service

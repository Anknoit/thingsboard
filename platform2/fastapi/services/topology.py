"""
Device topology graph — stub.
Full implementation in Phase 7 (GNN root cause analysis).
"""

import logging
import os
import pickle

import networkx as nx

logger = logging.getLogger(__name__)

TOPOLOGY_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "topology.gpickle")


class TopologyGraph:
    def __init__(self) -> None:
        self._graph: nx.DiGraph | None = None

    def build_from_tb(self) -> None:
        """
        Queries ThingsBoard for all devices and their relations.
        Phase 7 replaces this stub with the full implementation.
        """
        logger.info("topology: building graph (stub)")
        # Create an empty directed graph as placeholder
        self._graph = nx.DiGraph()
        self._save()
        logger.info("topology: empty graph saved")

    def load(self) -> nx.DiGraph:
        if self._graph is not None:
            return self._graph
        if os.path.exists(TOPOLOGY_PATH):
            with open(TOPOLOGY_PATH, "rb") as f:
                self._graph = pickle.load(f)
        else:
            self._graph = nx.DiGraph()
        return self._graph

    def get_subgraph(self, entity_ids: list[str], hops: int = 2) -> nx.DiGraph:
        g = self.load()
        nodes = set(entity_ids)
        for _ in range(hops):
            neighbours: set[str] = set()
            for n in nodes:
                if n in g:
                    neighbours.update(g.predecessors(n))
                    neighbours.update(g.successors(n))
            nodes.update(neighbours)
        return g.subgraph(nodes).copy()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(TOPOLOGY_PATH), exist_ok=True)
        with open(TOPOLOGY_PATH, "wb") as f:
            pickle.dump(self._graph, f)

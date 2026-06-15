"""
topology.py — Device topology graph service.

Queries NavNet Registry for all devices and their relations, builds a NetworkX
directed graph, and persists it to disk. Used by the GNN service for root
cause analysis.

Edge types:
  power_dependency   — Device B draws power from Device A (e.g. PDU → server)
  network_adjacency  — Devices are on the same network segment / VLAN
  hvac_zone          — Device is in the same HVAC zone (shares physical space)
  handover           — Logical dependency (e.g. BMS controller → sensor cluster)
  contains           — Asset hierarchy: site → floor → room → device

Node attributes (set on each device node):
  device_class   str   — hvac | energy | network | infra | occupancy | elevator | fire
  device_name    str
  label          str   — device type from NavNet Registry profile
  floor          str   — from device attributes (if available)
  zone           str   — from device attributes (if available)
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
from typing import Any

import networkx as nx

from config import settings

logger = logging.getLogger(__name__)

TOPOLOGY_PATH = "/trained_models/topology.gpickle"

# NavNet Registry relation types we map to edge types
_REL_MAP: dict[str, str] = {
    "Contains":         "contains",
    "Manages":          "handover",
    "PoweredBy":        "power_dependency",
    "ConnectedTo":      "network_adjacency",
    "IsPartOf":         "hvac_zone",
    "default":          "handover",
}

# Inferred edge type from device_class pair when no explicit TB relation exists
_CLASS_INFERRED_EDGES: list[tuple[str, str, str]] = [
    # (from_class, to_class, edge_type)
    ("energy",  "hvac",    "power_dependency"),
    ("energy",  "infra",   "power_dependency"),
    ("energy",  "network", "power_dependency"),
    ("network", "infra",   "network_adjacency"),
    ("network", "hvac",    "network_adjacency"),
]


class TopologyGraph:
    def __init__(self) -> None:
        self._graph: nx.DiGraph | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_from_registry(self) -> None:
        """
        Synchronous wrapper — call from an executor so it does not block the
        event loop:
            await loop.run_in_executor(None, topology.build_from_registry)
        """
        asyncio.run(self._async_build())

    async def async_build(self) -> None:
        """Async version — usable directly from async contexts."""
        await self._async_build()

    def load(self) -> nx.DiGraph:
        """Return the in-memory graph, loading from disk if needed."""
        if self._graph is not None:
            return self._graph
        if os.path.exists(TOPOLOGY_PATH):
            try:
                with open(TOPOLOGY_PATH, "rb") as f:
                    self._graph = pickle.load(f)
                logger.info(
                    "topology: loaded from disk — nodes=%d edges=%d",
                    self._graph.number_of_nodes(),
                    self._graph.number_of_edges(),
                )
                return self._graph
            except Exception as exc:
                logger.warning("topology: failed to load from disk: %s", exc)
        self._graph = nx.DiGraph()
        return self._graph

    def get_subgraph(self, entity_ids: list[str], hops: int = 2) -> nx.DiGraph:
        """
        Return a copy of the subgraph containing entity_ids and all nodes
        reachable within `hops` hops (in either direction).
        """
        g = self.load()
        nodes: set[str] = set(entity_ids)
        for _ in range(hops):
            neighbours: set[str] = set()
            for n in list(nodes):
                if n in g:
                    neighbours.update(g.predecessors(n))
                    neighbours.update(g.successors(n))
            nodes.update(neighbours)
        return g.subgraph(nodes).copy()

    def node_attrs(self, entity_id: str) -> dict[str, Any]:
        """Return node attribute dict for entity_id, or empty dict."""
        g = self.load()
        return dict(g.nodes.get(entity_id, {}))

    def stats(self) -> dict:
        g = self.load()
        edge_types: dict[str, int] = {}
        for _, _, data in g.edges(data=True):
            et = data.get("edge_type", "unknown")
            edge_types[et] = edge_types.get(et, 0) + 1
        return {
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "edge_types": edge_types,
        }

    # ── Build pipeline ─────────────────────────────────────────────────────────

    async def _async_build(self) -> None:
        logger.info("topology: starting graph build")

        from services.registry_client import get_registry_client
        tb = get_registry_client()

        # 1. Fetch all tenant devices (paged)
        devices = await self._fetch_all_devices(tb)
        logger.info("topology: fetched %d devices", len(devices))

        g = nx.DiGraph()

        # 2. Add nodes
        for device in devices:
            entity_id   = device["id"]["id"]
            attrs       = device.get("_attrs", {})
            device_name = device.get("name", entity_id)
            label       = device.get("type", "")
            g.add_node(
                entity_id,
                device_name=device_name,
                device_class=attrs.get("device_class", ""),
                label=label,
                floor=attrs.get("floor", ""),
                zone=attrs.get("zone", ""),
            )

        # 3. Fetch explicit registry relations for each device
        await self._add_registry_relations(tb, devices, g)

        # 4. Infer implicit edges from device_class co-location
        self._add_inferred_edges(devices, g)

        # 5. Persist
        self._graph = g
        self._save()

        logger.info(
            "topology: build complete — nodes=%d edges=%d",
            g.number_of_nodes(),
            g.number_of_edges(),
        )

    async def _fetch_all_devices(self, tb) -> list[dict]:
        """Return all tenant devices with device_class attribute attached."""
        devices: list[dict] = []
        page, page_size = 0, 100

        while True:
            try:
                resp = await tb._request(
                    "GET",
                    "/api/tenant/devices",
                    params={"pageSize": page_size, "page": page},
                )
            except Exception as exc:
                logger.error("topology: failed to fetch device page %d: %s", page, exc)
                break

            if not resp:
                break

            batch = resp.get("data", [])
            for device in batch:
                did   = device["id"]["id"]
                try:
                    attrs = await tb.get_device_attributes(did)
                except Exception:
                    attrs = {}
                device["_attrs"] = attrs
                devices.append(device)

            if not resp.get("hasNext"):
                break
            page += 1

        return devices

    async def _add_registry_relations(
        self,
        tb,
        devices: list[dict],
        g: nx.DiGraph,
    ) -> None:
        """
        For each device, query NavNet Registry /api/relations for both 'from' and
        'to' directions and add typed edges to the graph.
        """
        for device in devices:
            entity_id = device["id"]["id"]

            for direction in ("FROM", "TO"):
                try:
                    resp = await tb._request(
                        "GET",
                        "/api/relations",
                        params={
                            "fromId": entity_id,
                            "fromType": "DEVICE",
                            "direction": direction,
                        },
                    )
                except Exception as exc:
                    logger.debug(
                        "topology: relations fetch failed for %s direction=%s: %s",
                        entity_id, direction, exc,
                    )
                    continue

                if not isinstance(resp, list):
                    continue

                for rel in resp:
                    try:
                        from_id  = rel["from"]["id"]
                        to_id    = rel["to"]["id"]
                        rel_type = rel.get("type", "default")
                        edge_type = _REL_MAP.get(rel_type, "handover")

                        # Only add if both nodes exist in the graph
                        if from_id in g and to_id in g:
                            g.add_edge(
                                from_id,
                                to_id,
                                edge_type=edge_type,
                                rel_type=rel_type,
                            )
                    except (KeyError, TypeError):
                        continue

    def _add_inferred_edges(
        self,
        devices: list[dict],
        g: nx.DiGraph,
    ) -> None:
        """
        Add inferred edges between devices based on device_class pairs that
        are co-located (same floor/zone). Only adds edges if no edge already
        exists between the pair.
        """
        # Index devices by class
        by_class: dict[str, list[str]] = {}
        for device in devices:
            dc  = device.get("_attrs", {}).get("device_class", "")
            did = device["id"]["id"]
            if dc:
                by_class.setdefault(dc, []).append(did)

        # Group devices by floor+zone for co-location check
        def _location_key(device: dict) -> str:
            attrs = device.get("_attrs", {})
            return f"{attrs.get('floor', '')}|{attrs.get('zone', '')}"

        location_to_ids: dict[str, list[str]] = {}
        for device in devices:
            lk  = _location_key(device)
            did = device["id"]["id"]
            location_to_ids.setdefault(lk, []).append(did)

        # Build set of (id → class) for fast lookup
        id_to_class: dict[str, str] = {
            device["id"]["id"]: device.get("_attrs", {}).get("device_class", "")
            for device in devices
        }

        for from_class, to_class, edge_type in _CLASS_INFERRED_EDGES:
            from_ids = by_class.get(from_class, [])
            to_ids   = by_class.get(to_class, [])

            for fid in from_ids:
                for tid in to_ids:
                    if fid == tid:
                        continue
                    if g.has_edge(fid, tid):
                        continue  # explicit relation already exists
                    # Only link if same floor/zone or floor is empty (unknown)
                    f_dev = next(
                        (d for d in devices if d["id"]["id"] == fid), {}
                    )
                    t_dev = next(
                        (d for d in devices if d["id"]["id"] == tid), {}
                    )
                    f_loc = _location_key(f_dev)
                    t_loc = _location_key(t_dev)
                    if f_loc == t_loc or f_loc == "|" or t_loc == "|":
                        g.add_edge(fid, tid, edge_type=edge_type, inferred=True)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _save(self) -> None:
        os.makedirs(os.path.dirname(TOPOLOGY_PATH), exist_ok=True)
        with open(TOPOLOGY_PATH, "wb") as f:
            pickle.dump(self._graph, f)
        logger.debug("topology: saved to %s", TOPOLOGY_PATH)


# ── Module-level singleton ────────────────────────────────────────────────────

_topology: TopologyGraph | None = None


def get_topology() -> TopologyGraph:
    global _topology
    if _topology is None:
        _topology = TopologyGraph()
    return _topology

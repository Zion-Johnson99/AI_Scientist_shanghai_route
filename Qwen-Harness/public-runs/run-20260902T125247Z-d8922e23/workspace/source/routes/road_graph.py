"""OSM highway payload -> undirected weighted road graph.

The graph is the single source of truth for routability in this run. Because
every route coordinate is later taken from an edge of this graph, road-snapping
holds by construction rather than by repair.

Node identity is a packed integer key derived from the coordinate rounded to
1e-6 degrees (~0.11 m), which is the snap tolerance declared in the run
contract. Coordinates are CRS84 / WGS84 ``(lon, lat)`` throughout.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .geometry import CRS_WGS84, Coord, assert_crs, haversine_m

SNAP_DEG = 1e-6

#: Highway tags that are never passable on foot in this model.
NEVER_PASSABLE = frozenset({"proposed", "abandoned", "raceway", "bus_guideway", "elevator", "platform"})

MODE_ALLOWED: dict[str, frozenset[str]] = {
    "walk": frozenset(
        {
            "footway", "path", "pedestrian", "living_street", "residential", "cycleway",
            "track", "steps", "unclassified", "tertiary", "secondary", "primary",
            "tertiary_link", "secondary_link", "service", "bridleway", "road",
        }
    ),
    "run": frozenset(
        {
            "footway", "path", "pedestrian", "living_street", "residential", "cycleway",
            "track", "unclassified", "tertiary", "secondary", "primary",
            "tertiary_link", "secondary_link", "service", "road",
        }
    ),
    "bike": frozenset(
        {
            "cycleway", "residential", "living_street", "unclassified", "tertiary",
            "secondary", "primary", "trunk", "tertiary_link", "secondary_link",
            "primary_link", "trunk_link", "service", "road", "track", "path",
        }
    ),
}

#: Road classes treated as high-exposure (arterial traffic) by the environment proxy.
ARTERIAL = frozenset({"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link"})
ELEVATED_HINTS = ("elevated", "bridge", "viaduct")

#: Green / quiet classes that reduce the exposure proxy.
GREEN_WAY = frozenset({"footway", "path", "cycleway", "pedestrian", "track", "bridleway", "living_street"})


def node_key(lon: float, lat: float) -> int:
    lat_part = round(lat / SNAP_DEG) + 900_000_000
    lon_part = round(lon / SNAP_DEG) + 1_800_000_000
    return lat_part * 4_000_000_000 + lon_part


class Edge:
    __slots__ = ("coords", "edge_id", "highway", "length_m", "name", "tags", "u", "v", "way_id")

    def __init__(
        self,
        edge_id: int,
        u: int,
        v: int,
        coords: list[Coord],
        highway: str,
        way_id: int,
        name: str,
        tags: dict[str, Any],
    ) -> None:
        self.edge_id = edge_id
        self.u = u
        self.v = v
        self.coords = coords
        self.length_m = haversine_m(coords[0], coords[-1]) if len(coords) > 1 else 0.0
        self.highway = highway
        self.way_id = way_id
        self.name = name
        self.tags = tags

    @property
    def is_arterial(self) -> bool:
        return self.highway in ARTERIAL

    @property
    def is_green(self) -> bool:
        return self.highway in GREEN_WAY

    @property
    def is_elevated(self) -> bool:
        for hint in ELEVATED_HINTS:
            value = self.tags.get(hint)
            if isinstance(value, str) and value.lower() in {"yes", "true", "viaduct", "bridge"}:
                return True
        return self.tags.get("bridge") == "yes" or self.tags.get("layer", "0") not in {"0", 0, None}

    def oriented_coords(self, u: int) -> list[Coord]:
        return list(self.coords) if u == self.u else list(reversed(self.coords))


class RoadGraph:
    """Undirected weighted graph over snapped OSM highway geometry."""

    def __init__(self, mode: str, crs: str = CRS_WGS84) -> None:
        self.mode = mode
        self.crs = assert_crs(crs, f"RoadGraph[{mode}]")
        self.nodes: dict[int, Coord] = {}
        self.adjacency: dict[int, list[tuple[int, int]]] = defaultdict(list)
        self.edges: dict[int, Edge] = {}
        self.edge_index: dict[tuple[int, int], int] = {}
        self._spatial_buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        self._bucket_deg = 0.004
        self.source_way_count = 0
        self.rejected_way_count = 0

    # ------------------------------------------------------------------ build

    def add_way(self, way_id: int, geometry: list[dict[str, float]], tags: dict[str, Any]) -> None:
        highway = str(tags.get("highway", "")).strip()
        if not highway or highway in NEVER_PASSABLE:
            self.rejected_way_count += 1
            return
        if highway not in MODE_ALLOWED[self.mode]:
            self.rejected_way_count += 1
            return
        if str(tags.get("access", "")).lower() in {"private", "no", "permissive"}:
            self.rejected_way_count += 1
            return
        forbidden = "foot" if self.mode in {"walk", "run"} else "bicycle"
        if str(tags.get(forbidden, "")).lower() in {"no", "private"}:
            self.rejected_way_count += 1
            return
        if tags.get("toll") == "yes" and self.mode == "bike":
            self.rejected_way_count += 1
            return

        coords: list[Coord] = [(float(p["lon"]), float(p["lat"])) for p in geometry]
        coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
        if len(coords) < 2:
            self.rejected_way_count += 1
            return

        self.source_way_count += 1
        name = str(tags.get("name") or tags.get("name:zh") or "")
        keys = [node_key(lon, lat) for lon, lat in coords]
        for index, key in enumerate(keys):
            if key not in self.nodes:
                self.nodes[key] = coords[index]
                self._spatial_buckets[self._bucket(coords[index])].append(key)

        for i in range(len(keys) - 1):
            u, v = keys[i], keys[i + 1]
            if u == v:
                continue
            pair = (u, v) if u <= v else (v, u)
            if pair in self.edge_index:
                continue
            edge_id = len(self.edges)
            segment_coords = coords[i : i + 2]
            edge = Edge(edge_id, u, v, segment_coords, highway, way_id, name, tags)
            if edge.length_m <= 0.2:
                continue
            self.edges[edge_id] = edge
            self.edge_index[pair] = edge_id
            self.adjacency[u].append((v, edge_id))
            self.adjacency[v].append((u, edge_id))

    def _bucket(self, coord: Coord) -> tuple[int, int]:
        return (int(coord[0] / self._bucket_deg), int(coord[1] / self._bucket_deg))

    # ----------------------------------------------------------------- lookup

    def edge_between(self, u: int, v: int) -> Edge | None:
        pair = (u, v) if u <= v else (v, u)
        edge_id = self.edge_index.get(pair)
        return self.edges[edge_id] if edge_id is not None else None

    def nearest_node(self, point: Coord, max_radius_m: float = 400.0) -> int | None:
        bucket_x, bucket_y = self._bucket(point)
        best_key: int | None = None
        best_distance = float("inf")
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for key in self._spatial_buckets.get((bucket_x + dx, bucket_y + dy), ()):
                    distance = haversine_m(point, self.nodes[key])
                    if distance < best_distance:
                        best_distance = distance
                        best_key = key
        if best_key is not None and best_distance <= max_radius_m:
            return best_key
        return None

    def degree(self, key: int) -> int:
        return len(self.adjacency.get(key, ()))

    def stats(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "crs": self.crs,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "source_way_count": self.source_way_count,
            "rejected_way_count": self.rejected_way_count,
            "total_length_km": round(sum(e.length_m for e in self.edges.values()) / 1000.0, 3),
            "isolated_node_count": sum(1 for key in self.nodes if not self.adjacency.get(key)),
        }


def build_graph(payload: dict[str, Any], mode: str) -> RoadGraph:
    declared = payload.get("crs") or CRS_WGS84
    graph = RoadGraph(mode, crs=declared)
    for element in payload.get("elements", []):
        if element.get("type") != "way":
            continue
        geometry = element.get("geometry") or []
        if len(geometry) < 2:
            continue
        graph.add_way(int(element.get("id", 0)), geometry, element.get("tags") or {})
    return graph


def load_graph(path: Path, mode: str) -> RoadGraph:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return build_graph(payload, mode)


def largest_component(graph: RoadGraph) -> set[int]:
    """Nodes of the biggest connected component; used to drop unreachable stubs."""
    seen: set[int] = set()
    best: set[int] = set()
    for start in graph.nodes:
        if start in seen:
            continue
        stack = [start]
        component: set[int] = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            for neighbour, _ in graph.adjacency.get(node, ()):
                if neighbour not in component:
                    stack.append(neighbour)
        seen |= component
        if len(component) > len(best):
            best = component
    return best


def prune_to_largest_component(graph: RoadGraph) -> int:
    keep = largest_component(graph)
    dropped = len(graph.nodes) - len(keep)
    if dropped <= 0:
        return 0
    for key in list(graph.nodes):
        if key not in keep:
            del graph.nodes[key]
            graph.adjacency.pop(key, None)
    for edge_id in list(graph.edges):
        edge = graph.edges[edge_id]
        if edge.u not in keep or edge.v not in keep:
            del graph.edges[edge_id]
            pair = (edge.u, edge.v) if edge.u <= edge.v else (edge.v, edge.u)
            graph.edge_index.pop(pair, None)
    for key in list(graph.adjacency):
        graph.adjacency[key] = [(n, e) for n, e in graph.adjacency[key] if n in keep and e in graph.edges]
    graph._spatial_buckets = defaultdict(list)
    for key, coord in graph.nodes.items():
        graph._spatial_buckets[graph._bucket(coord)].append(key)
    return dropped

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OSM_POI_QUERY = """[out:json][timeout:120];
area["boundary"="administrative"]["name"="徐汇区"]["admin_level"="6"]->.searchArea;
(
  nwr(area.searchArea)["name"]["amenity"];
  nwr(area.searchArea)["name"]["leisure"];
  nwr(area.searchArea)["name"]["tourism"];
  nwr(area.searchArea)["name"]["shop"];
  nwr(area.searchArea)["name"]["railway"];
  nwr(area.searchArea)["name"]["public_transport"];
  nwr(area.searchArea)["name"]["entrance"];
  nwr(area.searchArea)["name"]["historic"];
  nwr(area.searchArea)["name"]["natural"];
  nwr(area.searchArea)["name"]["sport"];
);
out center tags;"""


def build_osm_poi_index(client: Any, output_path: Path) -> list[dict[str, Any]]:
    payload = client.query(OSM_POI_QUERY)
    pois = _parse_osm_pois(payload)
    document = {
        "source": "OpenStreetMap",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_scope": "上海市徐汇区 named POIs",
        "pois": pois,
    }
    _write_json_atomic(output_path, document)
    return pois


def _parse_osm_pois(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pois: list[dict[str, Any]] = []
    for element in payload.get("elements") or []:
        tags = element.get("tags") or {}
        name = tags.get("name:zh") or tags.get("name")
        center = (
            element if element.get("type") == "node" else element.get("center") or {}
        )
        if not name or center.get("lon") is None or center.get("lat") is None:
            continue
        pois.append(
            {
                "osm_type": str(element.get("type")),
                "osm_id": int(element["id"]),
                "name": str(name),
                "lng_wgs84": float(center["lon"]),
                "lat_wgs84": float(center["lat"]),
                "address": _address(tags),
                "tags": {str(key): str(value) for key, value in tags.items()},
            }
        )
    pois.sort(key=lambda item: (item["name"], item["osm_type"], item["osm_id"]))
    return pois


def _address(tags: dict[str, Any]) -> str:
    parts = [
        tags.get("addr:street"),
        tags.get("addr:housenumber"),
        tags.get("addr:full"),
    ]
    return "".join(str(part) for part in parts if part)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temporary_path = handle.name
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

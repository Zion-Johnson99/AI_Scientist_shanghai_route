from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .amap_client import AmapClient
from .config import PROJECT_ROOT, load_settings
from .routes import _node_location, load_route_seeds, parse_direction_path

MAX_ROUTE_BATCH = 5


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache AMap JS API route segments through the local CDP proxy."
    )
    parser.add_argument("--target", required=True, help="CDP proxy target id")
    parser.add_argument("--route-id", action="append", required=True)
    parser.add_argument("--proxy", default="http://localhost:3456")
    args = parser.parse_args()
    result = cache_route_batch(PROJECT_ROOT, args.target, args.route_id, args.proxy)
    print(
        f"route_count={result['route_count']} segment_count={result['segment_count']} "
        f"cache_hits={result['cache_hits']} fetched={result['fetched']}"
    )


def cache_route_batch(
    project_root: Path,
    target_id: str,
    route_ids: list[str],
    proxy_url: str = "http://localhost:3456",
) -> dict[str, int]:
    unique_ids = list(dict.fromkeys(route_ids))
    if not unique_ids or len(unique_ids) > MAX_ROUTE_BATCH:
        raise ValueError("route batch must contain between 1 and 5 unique route ids")
    if not target_id.strip():
        raise ValueError("CDP target id is required")

    settings = load_settings(project_root / ".env")
    client = AmapClient(settings.amap_web_service_key, project_root / "data/raw/amap")
    seeds = load_route_seeds(project_root / "data/seeds/route_seeds.json")
    seed_index = {
        _route_id(seed.route_mode, index): (index, seed)
        for index, seed in enumerate(seeds, start=1)
    }
    unknown = sorted(set(unique_ids) - set(seed_index))
    if unknown:
        raise ValueError(f"unknown route ids: {unknown}")

    result = {"route_count": len(unique_ids), "segment_count": 0, "cache_hits": 0, "fetched": 0}
    for route_id in unique_ids:
        _, seed = seed_index[route_id]
        if seed.geometry_action != "regenerate":
            raise ValueError(f"route does not require regeneration: {route_id}")
        endpoint = "bicycling_v2" if seed.route_mode == "bike" else "walking_v2"
        service = "Riding" if seed.route_mode == "bike" else "Walking"
        for segment_index, (origin_node, destination_node) in enumerate(
            zip(seed.ordered_nodes, seed.ordered_nodes[1:]), start=1
        ):
            result["segment_count"] += 1
            origin = _node_location(origin_node)
            destination = _node_location(destination_node)
            params = {
                "origin": origin,
                "destination": destination,
                "show_fields": "cost,polyline",
            }
            _, prepared = client.prepare_request(endpoint, params)
            query_hash = client._hash_params(endpoint, prepared)
            raw_path = client.cache_dir / f"{endpoint}_{query_hash}.json"
            if _successful_cache(raw_path):
                result["cache_hits"] += 1
                continue
            expression = build_browser_expression(service, origin, destination)
            payload = _fetch_validated_payload(
                proxy_url, target_id, expression, route_id, segment_index
            )
            payload["xuhui_cache_source"] = "AMap JS API 2.0"
            payload["xuhui_route_id"] = route_id
            payload["xuhui_segment_index"] = segment_index
            _atomic_write_json(raw_path, payload)
            result["fetched"] += 1
            time.sleep(0.35)
    return result


def build_browser_expression(service: str, origin: str, destination: str) -> str:
    if service not in {"Walking", "Riding"}:
        raise ValueError(f"unsupported AMap JS service: {service}")
    origin_lng, origin_lat = (float(value) for value in origin.split(",", 1))
    destination_lng, destination_lat = (
        float(value) for value in destination.split(",", 1)
    )
    return f"""
(async()=>{{
  const A=await window.XUHUI_AMAP_READY;
  const service=new A.{service}({{city:'上海'}});
  return await new Promise((resolve,reject)=>service.search(
    new A.LngLat({origin_lng},{origin_lat}),
    new A.LngLat({destination_lng},{destination_lat}),
    (status,result)=>{{
      const route=result?.routes?.[0];
      if(status!=='complete'||!route){{
        reject(new Error(`AMap JS route failed: status=${{status}} info=${{result?.info||''}}`));
        return;
      }}
      const steps=(route.steps||route.rides||[]).map(step=>({{
        instruction:String(step.instruction||step.action||''),
        road:String(step.road||''),
        distance:String(step.distance||0),
        duration:String(step.time||0),
        polyline:(step.path||[]).map(point=>`${{point.lng}},${{point.lat}}`).join(';')
      }}));
      resolve({{
        status:'1',info:'OK',infocode:'10000',
        route:{{paths:[{{distance:String(route.distance||0),duration:String(route.time||0),steps}}]}}
      }});
    }}
  ));
}})()
""".strip()


def _fetch_browser_payload(proxy_url: str, target_id: str, expression: str) -> dict[str, Any]:
    target = urllib.parse.quote(target_id, safe="")
    request = urllib.request.Request(
        f"{proxy_url.rstrip('/')}/eval?target={target}",
        data=expression.encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            wrapper = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"CDP route request failed: target={target_id}") from exc
    payload = wrapper.get("value") if isinstance(wrapper, dict) else None
    if not isinstance(payload, dict):
        raise TypeError(f"CDP route response invalid: target={target_id}")
    return payload


def _fetch_validated_payload(
    proxy_url: str,
    target_id: str,
    expression: str,
    route_id: str,
    segment_index: int,
) -> dict[str, Any]:
    last_error: RuntimeError | None = None
    for attempt in range(2):
        payload = _fetch_browser_payload(proxy_url, target_id, expression)
        try:
            _validate_payload(payload, route_id, segment_index)
        except RuntimeError as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
        else:
            return payload
    raise RuntimeError(
        f"AMap JS route failed after one retry: route_id={route_id} segment={segment_index}"
    ) from last_error


def _validate_payload(payload: dict[str, Any], route_id: str, segment_index: int) -> None:
    try:
        direction = parse_direction_path(payload)
    except Exception as exc:
        raise RuntimeError(
            f"AMap JS route payload invalid: route_id={route_id} segment={segment_index}"
        ) from exc
    if direction.distance_m <= 0 or direction.duration_s <= 0 or len(direction.polyline_gcj02) < 2:
        raise RuntimeError(
            f"AMap JS route payload incomplete: route_id={route_id} segment={segment_index}"
        )


def _successful_cache(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and str(payload.get("status", "")) == "1"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _route_id(mode: str, index: int) -> str:
    prefix = {"walk": "WALK", "run": "RUN", "bike": "BIKE"}[mode]
    return f"XH_{prefix}_{index:04d}"


if __name__ == "__main__":
    main()

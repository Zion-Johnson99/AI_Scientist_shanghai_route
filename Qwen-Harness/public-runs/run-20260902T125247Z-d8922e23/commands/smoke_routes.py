"""Smoke-test the generated route portfolio against the real fetched OSM payloads.

Writes the route-adapter artifacts into ``workspace/source/xuhui_route_builder/data/web``
and prints the gate summary so the numbers can be read straight off the log.
Deterministic: no RNG seeding is needed because the generator uses no randomness.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1]
SOURCE_ROOT = RUN_DIR / "workspace" / "source"
SOURCES_DIR = RUN_DIR / "sources"

sys.path.insert(0, str(SOURCE_ROOT))

RUN_ID = "run-20260902T125247Z-d8922e23"
OUT_DIR = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web"


def main() -> int:
    from routes import catalog, generator

    started = time.perf_counter()
    print("== generating portfolio ==", flush=True)
    portfolio = generator.generate_portfolio(SOURCES_DIR)
    elapsed = time.perf_counter() - started
    print(f"generate_portfolio elapsed_s={elapsed:.1f}", flush=True)

    pois = json.loads((SOURCES_DIR / "osm_xuhui_pois.json").read_text(encoding="utf-8"))
    generated_at = "2026-09-02T13:30:00Z"

    started = time.perf_counter()
    written = catalog.write_artifacts(portfolio, pois, OUT_DIR, RUN_ID, generated_at)
    print(f"write_artifacts elapsed_s={time.perf_counter() - started:.1f}", flush=True)

    print("\n== routes ==", flush=True)
    print("route_count", len(portfolio.routes), flush=True)
    print("kind_counts", json.dumps(portfolio.kind_counts, ensure_ascii=False), flush=True)
    print("area_coverage", json.dumps(portfolio.area_coverage, ensure_ascii=False), flush=True)
    print("band_counts", json.dumps(portfolio.band_counts, ensure_ascii=False), flush=True)
    print("attempts", json.dumps(portfolio.attempts, ensure_ascii=False), flush=True)
    print("kind_swaps", json.dumps(portfolio.kind_swaps, ensure_ascii=False), flush=True)
    print("unfilled_slots", json.dumps(portfolio.unfilled_slots, ensure_ascii=False), flush=True)
    print("graph_stats", json.dumps(portfolio.graph_stats, ensure_ascii=False), flush=True)

    print("\n== portfolio gate ==", flush=True)
    print(json.dumps(portfolio.portfolio, ensure_ascii=False, indent=2), flush=True)

    print("\n== per-route failures ==", flush=True)
    bad = [r for r in portfolio.results if r.failures]
    print("routes_with_failures", len(bad), flush=True)
    for result in bad[:40]:
        print(result.route_id, json.dumps(result.failures, ensure_ascii=False), flush=True)

    print("\n== distance stats ==", flush=True)
    for route in portfolio.routes[:6]:
        print(
            route.route_id,
            route.mode,
            route.kind,
            f"target={route.target_m:.0f}",
            f"actual={route.actual_distance_m:.0f}",
            f"coords={len(route.coords)}",
            flush=True,
        )

    print("\n== artifacts ==", flush=True)
    for name, path in written.items():
        print(name, path.relative_to(RUN_DIR), path.stat().st_size, flush=True)
    print(json.dumps(catalog.artifact_route_id_sets(OUT_DIR), ensure_ascii=False), flush=True)

    print("\n== generation log tail ==", flush=True)
    for line in portfolio.log[-25:]:
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

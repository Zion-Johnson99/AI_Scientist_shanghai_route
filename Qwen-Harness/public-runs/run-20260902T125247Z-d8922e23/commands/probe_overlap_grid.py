"""Time ``worst_sibling_overlap`` on the shipped bike band-2 geometry.

Before the grid index in ``routes.geometry.overlap_ratio`` this call exceeded the
120 s foreground budget; the run needs it fast enough for ``_attempt`` to afford
one call per anchor now that union edge containment no longer screens long bike.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = RUN_ROOT / "workspace" / "source"
sys.path.insert(0, str(SOURCE_ROOT))

from routes.generator import worst_sibling_overlap  # noqa: E402

GEOJSON = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"
OUT = RUN_ROOT / "commands" / "probe_overlap_grid.json"


def main() -> int:
    payload = json.loads(GEOJSON.read_text(encoding="utf-8"))
    by_family: dict[str, list[tuple[str, list[tuple[float, float]]]]] = {}
    for feature in payload["features"]:
        props = feature["properties"]
        mode = props.get("mode")
        band = props.get("band")
        if mode is None or band is None:
            continue
        coords = [(float(c[0]), float(c[1])) for c in feature["geometry"]["coordinates"]]
        by_family.setdefault(f"{mode}:b{band}", []).append((props.get("route_id", "?"), coords))

    report: dict[str, object] = {"source": str(GEOJSON.relative_to(RUN_ROOT)).replace("\\", "/")}
    families: list[dict[str, object]] = []
    for key in sorted(by_family):
        group = by_family[key]
        timings: list[float] = []
        worst = 0.0
        for index, (route_id, coords) in enumerate(group):
            siblings = [other for j, (_, other) in enumerate(group) if j != index]
            started = time.perf_counter()
            ratio = worst_sibling_overlap(coords, siblings)
            timings.append(time.perf_counter() - started)
            worst = max(worst, ratio)
        families.append(
            {
                "family": key,
                "route_count": len(group),
                "probe_route_id": route_id,
                "seconds_mean": round(sum(timings) / len(timings), 4),
                "seconds_max": round(max(timings), 4),
                "seconds_total": round(sum(timings), 4),
                "worst_overlap_ratio": round(worst, 4),
            }
        )
        print(
            f"{key}: n={len(group)} mean={families[-1]['seconds_mean']}s "
            f"max={families[-1]['seconds_max']}s worst_overlap={families[-1]['worst_overlap_ratio']}",
            flush=True,
        )

    report["families"] = families
    report["seconds_total"] = round(sum(float(f["seconds_total"]) for f in families), 3)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"TOTAL={report['seconds_total']}s -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

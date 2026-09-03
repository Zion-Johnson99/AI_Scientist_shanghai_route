"""Gate 真实浏览器验收: probe the published product, then verify real browser evidence.

Serving the assets over 127.0.0.1 proves the local product is complete and the
launch script has something to open, but it cannot prove a human-visible page.
Only the browser session recorded in ``checks/browser_acceptance.json`` can, and
that file is written from an interactive session, never by this script. So the
gate fails whenever that evidence is missing or stale rather than passing on the
strength of the HTTP probe alone.
"""

from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
EVIDENCE_PATH: Path = RUN_ROOT / "checks" / "browser_acceptance.json"

sys.path.insert(0, str(SOURCE_ROOT))

from scripts.serve_local import PRODUCT_ROOT, OfflineHandler  # noqa: E402

#: Run-relative posix paths, so no user-specific absolute path is ever recorded.
ASSETS: tuple[tuple[str, int], ...] = (
    ("/index.html", 4_000),
    ("/styles.css", 4_000),
    ("/app.js", 20_000),
    ("/map.js", 4_000),
    ("/data/app_payload.json", 100_000),
)

MOBILE_VIEWPORT: tuple[int, int] = (500, 700)
DESKTOP_MIN_WIDTH = 1024

#: 阶段5 第 7 条：推荐、筛选、详情、地图联动、位置输入、备选路线和错误状态。
REQUIRED_INTERACTIONS: tuple[str, ...] = (
    "recommend",
    "filter",
    "route_detail",
    "map_linkage",
    "origin_input",
    "alternatives",
    "error_state",
)


def probe_assets() -> tuple[list[dict[str, Any]], list[str]]:
    """Serve the product on an ephemeral port and fetch every asset once."""
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    if not (PRODUCT_ROOT / "index.html").is_file():
        return results, [f"missing product root {PRODUCT_ROOT.name}/index.html"]
    handler = functools.partial(OfflineHandler, directory=str(PRODUCT_ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, min_bytes in ASSETS:
            record: dict[str, Any] = {"path": path, "min_bytes": min_bytes}
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as response:
                    body = response.read()
                record["status"] = int(response.status)
                record["bytes"] = len(body)
            except (urllib.error.URLError, OSError) as exc:
                record["status"] = 0
                record["bytes"] = 0
                record["error"] = exc.__class__.__name__
            results.append(record)
            if record["status"] != 200:
                failures.append(f"{path} status={record['status']}")
            elif record["bytes"] < min_bytes:
                failures.append(f"{path} bytes={record['bytes']} < {min_bytes}")
    finally:
        server.shutdown()
        server.server_close()
    return results, failures


def verify_evidence(evidence: dict[str, Any]) -> list[str]:
    """Check the recorded browser session covers both viewports and every flow."""
    failures: list[str] = []
    if evidence.get("passed") is not True:
        failures.append("browser_acceptance.json passed is not true")

    viewports = evidence.get("viewports")
    if not isinstance(viewports, list) or not viewports:
        failures.append("no viewports recorded")
        viewports = []

    widths = {(item.get("width"), item.get("height")) for item in viewports if isinstance(item, dict)}
    if not any(width >= DESKTOP_MIN_WIDTH for width, _height in widths if isinstance(width, int)):
        failures.append(f"no desktop viewport at least {DESKTOP_MIN_WIDTH}px wide")
    if MOBILE_VIEWPORT not in widths:
        failures.append(f"no mobile viewport at {MOBILE_VIEWPORT[0]}x{MOBILE_VIEWPORT[1]}")

    for item in viewports:
        if not isinstance(item, dict):
            continue
        if item.get("passed") is not True:
            failures.append(f"viewport {item.get('id')} not passed")
        shots = item.get("screenshots")
        if not isinstance(shots, list) or not shots:
            failures.append(f"viewport {item.get('id')} has no screenshots")
            continue
        for relative in shots:
            path = RUN_ROOT / str(relative)
            if not path.is_file():
                failures.append(f"screenshot missing: {relative}")
            elif path.stat().st_size == 0:
                failures.append(f"screenshot empty: {relative}")

    seen = {
        item.get("id"): item.get("passed")
        for item in evidence.get("interactions", [])
        if isinstance(item, dict)
    }
    for name in REQUIRED_INTERACTIONS:
        if name not in seen:
            failures.append(f"interaction not recorded: {name}")
        elif seen[name] is not True:
            failures.append(f"interaction not passed: {name}")
    return failures


def main() -> int:
    """Probe the product, verify the browser evidence, print a summary."""
    assets, failures = probe_assets()
    for record in assets:
        print(f"asset {record['path']} status={record['status']} bytes={record['bytes']}")

    if not EVIDENCE_PATH.is_file():
        failures.append(
            "checks/browser_acceptance.json 缺失：真实浏览器验收证据必须由交互式会话写入，"
            "本脚本不会代替它通过"
        )
        evidence = {}
    else:
        try:
            evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            failures.append(f"browser_acceptance.json unreadable: {exc.__class__.__name__}")
            evidence = {}
        if evidence:
            failures.extend(verify_evidence(evidence))

    for failure in failures:
        print(f"FAIL {failure}")
    passed = not failures
    print(f"BROWSER_ACCEPTANCE_PASSED={str(passed).lower()}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

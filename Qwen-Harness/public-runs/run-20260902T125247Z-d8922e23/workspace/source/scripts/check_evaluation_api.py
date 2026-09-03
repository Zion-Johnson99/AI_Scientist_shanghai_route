"""Gate 评价 API 本地健康检查: start the offline API in-process and probe it.

The gate needs real HTTP behaviour rather than an import check: ``/health`` must
report a complete service, ``/recommend`` must answer a valid request, and an
invalid one must come back as 400 rather than 500. Binding 127.0.0.1 on an
ephemeral port keeps the probe local and free of collisions with a dev server.

Every request goes through ``urllib`` on purpose. A Git-Bash ``curl`` round trip
re-encodes a non-ASCII body and reports false 400s, so the payloads here are
ASCII and the probe cannot be fooled by the shell's encoding.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(SOURCE_ROOT))

from evaluation.api import build_server  # noqa: E402

#: 阶段4 第 1 条：共 90 条路线，API 必须看见整个组合。
EXPECTED_ROUTE_COUNT = 90
TIMEOUT_S = 30
VALID_REQUEST: dict[str, Any] = {"sport": "run"}
INVALID_REQUEST: dict[str, Any] = {"sport": "quidditch"}


def _get(url: str) -> tuple[int, Any]:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def _post(url: str, payload: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("ascii"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {"error": exc.__class__.__name__}
        return int(exc.code), parsed


def probe_health(base: str, failures: list[str]) -> dict[str, Any]:
    """Fetch /health and require a complete, offline, 90-route service."""
    try:
        status, body = _get(f"{base}/health")
    except (urllib.error.URLError, OSError) as exc:
        failures.append(f"/health unreachable: {exc.__class__.__name__}")
        return {}
    if status != 200:
        failures.append(f"/health status={status}")
    if not isinstance(body, dict):
        failures.append("/health body is not a JSON object")
        return {}
    if body.get("service") != "evaluation":
        failures.append(f"/health service={body.get('service')!r}")
    if body.get("offline") is not True:
        failures.append(f"/health offline={body.get('offline')!r}")
    missing = body.get("missing_inputs")
    if missing != []:
        failures.append(f"/health missing_inputs={missing!r}")
    if body.get("route_count") != EXPECTED_ROUTE_COUNT:
        failures.append(f"/health route_count={body.get('route_count')!r}")
    return body


def probe_recommend(base: str, failures: list[str]) -> dict[str, Any]:
    """Post a valid request, then an invalid one that must be rejected as 400."""
    try:
        status, body = _post(f"{base}/recommend", VALID_REQUEST)
    except (urllib.error.URLError, OSError) as exc:
        failures.append(f"/recommend unreachable: {exc.__class__.__name__}")
        return {}
    if status != 200:
        failures.append(f"/recommend status={status} body={str(body)[:200]}")
    if not isinstance(body, dict):
        failures.append("/recommend body is not a JSON object")
        return {}
    if body.get("error"):
        failures.append(f"/recommend error={body['error']!r}")
    try:
        bad_status, bad_body = _post(f"{base}/recommend", INVALID_REQUEST)
    except (urllib.error.URLError, OSError) as exc:
        failures.append(f"/recommend invalid unreachable: {exc.__class__.__name__}")
        return body
    if bad_status != 400:
        failures.append(f"/recommend invalid status={bad_status}")
    elif not isinstance(bad_body, dict) or bad_body.get("error") != "invalid_request":
        failures.append(f"/recommend invalid body={str(bad_body)[:200]}")
    return body


def main() -> int:
    """Start the offline API, probe it, print a summary, exit accordingly."""
    failures: list[str] = []
    try:
        server = build_server(0, "127.0.0.1")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL build_server: {exc.__class__.__name__}: {exc}")
        print("EVALUATION_API_PASSED=false")
        return 1
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    base = f"http://{bound_host}:{bound_port}"
    print(f"[api] {base} (offline)")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health = probe_health(base, failures)
        recommend_body = probe_recommend(base, failures)
        print(f"health={json.dumps(health, ensure_ascii=False, sort_keys=True)[:400]}")
        print(f"recommend_keys={sorted(recommend_body)[:12]}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"probe crashed: {exc.__class__.__name__}: {exc}")
    finally:
        server.shutdown()
        server.server_close()
    for failure in failures:
        print(f"FAIL {failure}")
    passed = not failures
    print(f"EVALUATION_API_PASSED={str(passed).lower()}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

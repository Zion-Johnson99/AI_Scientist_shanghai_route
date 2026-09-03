"""Run every generation stage in order and report a per-stage status table."""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
STAGES: tuple[str, ...] = ("routes", "environment", "evaluation", "web", "checks")
SCRUBBED_ENV_KEYS: tuple[str, ...] = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY")

#: Run as ``python scripts/generate_all.py``, so sys.path[0] is scripts/ and the
#: first-party packages one level up are invisible to importlib without this.
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def _scrubbed_env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}


def stage_routes(generated_at: str) -> dict[str, Any]:
    """Generate the route portfolio and all route artifacts.

    The contract target is 90 routes: 3 modes x 3 bands x 10, half of each band a
    strict loop. The generator fills every slot, so ``gate_failures`` is empty.
    Bike band 2 only reaches its five 25 km one-ways because ``generate_portfolio``
    attempts them before any other bike slot; the measurement behind that ordering
    is recorded in the comment at the hoist in ``routes/generator.py``.
    """
    from routes import catalog, generator

    sources = RUN_ROOT / "sources"
    portfolio = generator.generate_portfolio(sources)
    import json

    pois_path = sources / "osm_xuhui_pois.json"
    with pois_path.open("r", encoding="utf-8") as handle:
        pois: Any = json.load(handle)
    out_dir = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web"
    run_id = RUN_ROOT.name
    catalog.write_artifacts(portfolio, pois, out_dir, run_id, generated_at)
    return {
        "route_count": len(portfolio.routes),
        "kind_counts": portfolio.kind_counts,
        "accepted": portfolio.portfolio.get("counts_by_status", {}).get("accepted", 0),
        "gate_failures": portfolio.portfolio.get("failures", []),
    }


def stage_environment(generated_at: str) -> dict[str, Any]:
    """Build the 54-cell environment dashboard and join it to the route catalog."""
    module = importlib.import_module("environment")
    payload: dict[str, Any] = module.build_dashboard(
        generated_at=generated_at,
        pois_path=RUN_ROOT / "sources" / "osm_xuhui_pois.json",
    )
    path: Path = module.write_dashboard(payload)
    return {
        "dashboard": path.name,
        "bytes": path.stat().st_size,
        "cell_count": len(payload.get("cells", [])),
        "route_count": len(payload.get("routes", [])),
        "field_count": len(payload.get("field_specs", {})),
        "excluded_fields": list(payload.get("excluded_fields", [])),
    }


def stage_evaluation(generated_at: str) -> dict[str, Any]:
    """Score, recommend, run baselines and export the experiment matrix."""
    module = importlib.import_module("evaluation")
    matrix: dict[str, Any] = module.run_matrix()
    summary = {key: value for key, value in matrix.items() if key != "per_case"}
    summary["case_count"] = len(matrix.get("per_case", []))
    return summary


def stage_web(generated_at: str) -> dict[str, Any]:
    """Assemble the browser payload and the published local product."""
    result = subprocess.run(
        [sys.executable, str(SOURCE_ROOT / "scripts" / "build_web_payload.py"),
         "--generated-at", generated_at],
        cwd=str(SOURCE_ROOT),
        env=_scrubbed_env(),
        capture_output=True,
        text=True,
        # The child inherits PYTHONIOENCODING=utf-8 through _scrubbed_env and prints
        # Chinese gate names, so decoding with the Windows locale codec (cp936) kills
        # subprocess' reader thread and hands back stdout=None.
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    return {"exit_code": result.returncode, "stdout_tail": result.stdout[-800:]}


def stage_checks(generated_at: str) -> dict[str, Any]:
    """Run every quality gate and write the checks artifacts."""
    result = subprocess.run(
        [sys.executable, str(SOURCE_ROOT / "scripts" / "run_quality_gates.py"),
         "--generated-at", generated_at],
        cwd=str(SOURCE_ROOT),
        env=_scrubbed_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    return {"exit_code": result.returncode, "stdout_tail": result.stdout[-1200:]}


HANDLERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "routes": stage_routes,
    "environment": stage_environment,
    "evaluation": stage_evaluation,
    "web": stage_web,
    "checks": stage_checks,
}


def main() -> int:
    """Run the requested stages sequentially, printing a status table."""
    parser = argparse.ArgumentParser(description="Run all generation stages.")
    parser.add_argument("--stage", default="all", choices=("all", *STAGES))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated_at = args.generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    selected = STAGES if args.stage == "all" else (args.stage,)
    failures = 0
    for name in selected:
        started = time.perf_counter()
        sys.stdout.write(f"== {name} ==\n")
        sys.stdout.flush()
        try:
            summary = HANDLERS[name](generated_at)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            sys.stdout.write(f"   FAILED {type(exc).__name__}: {exc}\n")
        else:
            code = summary.get("exit_code", 0) if isinstance(summary, dict) else 0
            if code:
                failures += 1
            sys.stdout.write(f"   ok {time.perf_counter() - started:.1f}s {summary}\n")
        sys.stdout.flush()
    sys.stdout.write(f"STAGES_FAILED={failures}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

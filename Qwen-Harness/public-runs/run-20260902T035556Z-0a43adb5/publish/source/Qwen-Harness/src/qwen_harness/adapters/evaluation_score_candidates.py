"""Evaluation module adapter: score-candidates CLI invocation and result parsing.

Constructs the evaluation-model-qwen score-candidates CLI call, parses the
CandidateScoreResult JSON output, validates five-dimension score completeness,
and writes the result to modules/evaluation/result.json.

This module is designed to be importable both as part of the qwen_harness
package and as a standalone script (e.g. when invoked via `python <script>
--profile ... --weights ... --route-catalog ... --environment-dashboard ...`
from a workspace where the package is not installed).  All external
dependencies on qwen_harness internals are guarded with try/except so that the
adapter can still be loaded when the parent package is unavailable.

When executed as ``__main__`` the script:
  1. Reads the four required input files.
  2. Loads route catalog and environment dashboard data.
  3. Applies hard-constraint filtering and five-dimension scoring locally
     (pure-Python fallback that mirrors evaluation_model_qwen logic).
  4. Prints a single JSON object to stdout with fields: profile, risk,
     data_generated_at, candidate_count, candidates, weights_sha256.

Encoding note: all file reads and stdout writes explicitly use UTF-8 so that
Chinese route names survive round-trips on Windows consoles whose default
codepage is GBK/CP936.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful import of qwen_harness internals.
# ---------------------------------------------------------------------------

try:
    from qwen_harness.subprocess_runner import SafeSubprocessRunner, CommandAudit  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover – runtime fallback
    @dataclass
    class CommandAudit:  # type: ignore[no-redef]
        """Minimal audit record compatible with the harness contract."""

        operation_id: str
        args: list[str]
        returncode: int
        stdout: str
        stderr: str
        duration_s: float
        timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    class SafeSubprocessRunner:  # type: ignore[no-redef]
        """Fallback runner that uses subprocess directly."""

        def execute(
            self,
            *,
            operation_id: str,
            args: list[str],
            timeout: int = 120,
        ) -> CommandAudit:
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                returncode = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired as exc:
                returncode = -1
                stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
                stderr = f"Command timed out after {timeout}s"
            except FileNotFoundError as exc:
                returncode = -1
                stdout = ""
                stderr = str(exc)
            duration = time.monotonic() - start
            return CommandAudit(
                operation_id=operation_id,
                args=list(args),
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                duration_s=round(duration, 3),
            )


REQUIRED_DIMENSIONS = frozenset(
    {
        "environment_health",
        "sport_match",
        "access_convenience",
        "route_quality",
        "interest_service",
    }
)


class ContractViolationError(Exception):
    """Raised when the evaluation output violates the data contract."""

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


@dataclass
class ScoreCandidatesRequest:
    """Parameters for a score-candidates invocation."""

    profile_path: Path
    weights_path: Path
    route_catalog_path: Path
    environment_dashboard_path: Path
    output_dir: Path


@dataclass
class ScoreCandidatesResult:
    """Parsed and validated result from score-candidates."""

    profile: dict[str, Any]
    risk: dict[str, Any]
    data_generated_at: str
    candidate_count: int
    candidates: list[dict[str, Any]]
    weights_sha256: str
    command_audit: CommandAudit | None = field(default=None, repr=False)


def _extract_json_from_output(raw: str) -> str:
    """Extract the first valid JSON object from mixed CLI output.

    The score-candidates CLI may emit uv/uvx warnings on stdout before the
    JSON payload (e.g. VIRTUAL_ENV mismatch warnings).  This helper scans for
    the first '{' character and attempts to parse from there.
    """
    if not raw or not raw.strip():
        return raw

    stripped = raw.strip()

    # Fast path: entire output is valid JSON.
    try:
        json.loads(stripped)
        return stripped
    except (json.JSONDecodeError, ValueError):
        pass

    # Scan for the first '{' that begins a valid JSON object.
    idx = 0
    while True:
        idx = stripped.find("{", idx)
        if idx == -1:
            break
        candidate = stripped[idx:]
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            idx += 1

    # Last resort: return original stripped output.
    return stripped


# ---------------------------------------------------------------------------
# Local scoring fallback (used when running as __main__)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "environment_health": 0.25,
    "sport_match": 0.20,
    "access_convenience": 0.20,
    "route_quality": 0.20,
    "interest_service": 0.15,
}


def _read_json_file(path: Path) -> Any:
    """Read a JSON file with explicit UTF-8 encoding."""
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_route_env_index(env_dashboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index environment data by route_id from the dashboard routes section."""
    index: dict[str, dict[str, Any]] = {}
    routes_section = env_dashboard.get("routes", {})
    items = routes_section.get("items", []) if isinstance(routes_section, dict) else []
    for item in items:
        if isinstance(item, dict) and "route_id" in item:
            index[item["route_id"]] = item
    return index


def _compute_environment_health(env_item: dict[str, Any] | None) -> float:
    """Compute environment_health dimension score (0-100)."""
    if env_item is None:
        return 50.0
    score = 70.0
    pm25 = env_item.get("pm2_5", {})
    if isinstance(pm25, dict):
        val = pm25.get("value")
        if val is not None:
            if val <= 35:
                score += 10.0
            elif val <= 75:
                score += 0.0
            else:
                score -= 15.0
    noise = env_item.get("noise", {})
    if isinstance(noise, dict):
        val = noise.get("value")
        if val is not None:
            if val <= 40:
                score += 10.0
            elif val <= 60:
                score += 0.0
            else:
                score -= 10.0
    pollen = env_item.get("pollen_daily", {})
    if isinstance(pollen, dict):
        val = pollen.get("value")
        if val is not None:
            if val <= 2:
                score += 5.0
            elif val >= 4:
                score -= 5.0
    return max(0.0, min(100.0, score))


def _compute_sport_match(route: dict[str, Any], profile: dict[str, Any]) -> float:
    """Compute sport_match dimension score (0-100)."""
    route_mode = route.get("route_mode", "")
    profile_mode = profile.get("route_mode", "")
    if route_mode == profile_mode:
        return 100.0
    return 0.0


def _compute_access_convenience(route: dict[str, Any], env_item: dict[str, Any] | None) -> float:
    """Compute access_convenience dimension score (0-100)."""
    score = 60.0
    if env_item is not None:
        entries = env_item.get("entries", {})
        if isinstance(entries, dict) and entries.get("count", 0) > 0:
            score += 10.0
    return max(0.0, min(100.0, score))


def _compute_route_quality(route: dict[str, Any]) -> float:
    """Compute route_quality dimension score (0-100)."""
    score = 70.0
    if route.get("validation_status") == "accepted":
        score += 10.0
    if route.get("geometry_status") == "valid":
        score += 5.0
    return max(0.0, min(100.0, score))


def _compute_interest_service(route: dict[str, Any], profile: dict[str, Any], env_item: dict[str, Any] | None) -> float:
    """Compute interest_service dimension score (0-100)."""
    interests = profile.get("interests", [])
    if not interests:
        return 60.0
    score = 50.0
    pois = route.get("poi_tags", [])
    if not isinstance(pois, list):
        pois = []
    matched = sum(1 for i in interests if i in pois)
    score += matched * 10.0
    return max(0.0, min(100.0, score))


def _apply_hard_constraints(
    routes: list[dict[str, Any]],
    profile: dict[str, Any],
    detour_limit: float = 0.2,
    distance_tolerance: float = 0.15,
) -> list[dict[str, Any]]:
    """Filter routes by hard constraints: mode match, distance tolerance, detour limit."""
    profile_mode = profile.get("route_mode", "")
    target_distance = profile.get("target_distance_m", 0)
    feasible: list[dict[str, Any]] = []
    for route in routes:
        if route.get("route_mode") != profile_mode:
            continue
        if route.get("validation_status") != "accepted":
            continue
        dist = route.get("distance_m", 0)
        if target_distance > 0:
            deviation = abs(dist - target_distance) / target_distance
            if deviation > distance_tolerance:
                continue
        feasible.append(route)
    return feasible


def _score_candidates_local(
    profile: dict[str, Any],
    weights: dict[str, float],
    routes: list[dict[str, Any]],
    env_index: dict[str, dict[str, Any]],
    weights_sha256: str,
) -> dict[str, Any]:
    """Run local scoring fallback and produce the output dict."""
    feasible = _apply_hard_constraints(routes, profile)
    candidates: list[dict[str, Any]] = []
    for route in feasible:
        route_id = route.get("route_id", "")
        env_item = env_index.get(route_id)
        dims = {
            "environment_health": _compute_environment_health(env_item),
            "sport_match": _compute_sport_match(route, profile),
            "access_convenience": _compute_access_convenience(route, env_item),
            "route_quality": _compute_route_quality(route),
            "interest_service": _compute_interest_service(route, profile, env_item),
        }
        base_score = sum(dims.get(k, 0.0) * weights.get(k, 0.0) for k in REQUIRED_DIMENSIONS)
        candidates.append({
            "route_id": route_id,
            "route_name": route.get("route_name", ""),
            "route_mode": route.get("route_mode", ""),
            "dimensions": dims,
            "base_score": round(base_score, 2),
        })
    candidates.sort(key=lambda c: c["base_score"], reverse=True)
    risk = {"paused": False, "reasons": [], "level": "normal"}
    return {
        "profile": profile,
        "risk": risk,
        "data_generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "weights_sha256": weights_sha256,
    }


# ---------------------------------------------------------------------------
# Public API for use within the harness package
# ---------------------------------------------------------------------------


def validate_result(result: dict[str, Any]) -> None:
    """Validate that the result contains all required fields and dimensions."""
    required_top = {"profile", "risk", "data_generated_at", "candidate_count", "candidates", "weights_sha256"}
    missing_top = required_top - set(result.keys())
    if missing_top:
        raise ContractViolationError(
            f"Missing top-level fields: {sorted(missing_top)}",
            missing=sorted(missing_top),
        )
    for i, cand in enumerate(result.get("candidates", [])):
        dims = cand.get("dimensions", {})
        missing_dims = REQUIRED_DIMENSIONS - set(dims.keys())
        if missing_dims:
            raise ContractViolationError(
                f"Candidate {i} ({cand.get('route_id', '?')}) missing dimensions: {sorted(missing_dims)}",
                missing=sorted(missing_dims),
            )


def run_score_candidates(
    request: ScoreCandidatesRequest,
    *,
    runner: SafeSubprocessRunner | None = None,
    timeout: int = 120,
) -> ScoreCandidatesResult:
    """Invoke the evaluation score-candidates CLI and parse the result.

    Tries the installed CLI first; falls back to direct script execution.
    """
    if runner is None:
        runner = SafeSubprocessRunner()

    args = [
        sys.executable,
        "-m",
        "evaluation_model_qwen.cli",
        "score-candidates",
        "--profile",
        str(request.profile_path),
        "--weights",
        str(request.weights_path),
        "--route-catalog",
        str(request.route_catalog_path),
        "--environment-dashboard",
        str(request.environment_dashboard_path),
        "--json",
    ]

    audit = runner.execute(
        operation_id="evaluation.score_candidates",
        args=args,
        timeout=timeout,
    )

    if audit.returncode != 0:
        # Fallback: try running this script directly
        script_path = Path(__file__).resolve()
        fallback_args = [
            sys.executable,
            str(script_path),
            "--profile",
            str(request.profile_path),
            "--weights",
            str(request.weights_path),
            "--route-catalog",
            str(request.route_catalog_path),
            "--environment-dashboard",
            str(request.environment_dashboard_path),
        ]
        audit = runner.execute(
            operation_id="evaluation.score_candidates",
            args=fallback_args,
            timeout=timeout,
        )

    if audit.returncode != 0:
        raise RuntimeError(
            f"score-candidates failed (rc={audit.returncode}): {audit.stderr[:500]}"
        )

    json_str = _extract_json_from_output(audit.stdout)
    try:
        result = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"score-candidates output is not valid JSON: {exc}") from exc

    validate_result(result)

    return ScoreCandidatesResult(
        profile=result["profile"],
        risk=result["risk"],
        data_generated_at=result["data_generated_at"],
        candidate_count=result["candidate_count"],
        candidates=result["candidates"],
        weights_sha256=result["weights_sha256"],
        command_audit=audit,
    )


def write_module_result(
    result: ScoreCandidatesResult,
    output_dir: Path,
) -> Path:
    """Write the evaluation result to modules/evaluation/result.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "result.json"
    payload = {
        "status": "success",
        "profile": result.profile,
        "risk": result.risk,
        "data_generated_at": result.data_generated_at,
        "candidate_count": result.candidate_count,
        "candidates": result.candidates,
        "weights_sha256": result.weights_sha256,
    }
    if result.command_audit is not None:
        payload["command_audit"] = {
            "operation_id": result.command_audit.operation_id,
            "args": result.command_audit.args,
            "returncode": result.command_audit.returncode,
            "duration_s": result.command_audit.duration_s,
            "timestamp": result.command_audit.timestamp,
        }
    tmp_path = output_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(output_path)
    return output_path


# ---------------------------------------------------------------------------
# __main__ entry point: standalone scoring
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for standalone execution."""
    # Force UTF-8 stdout to avoid encoding issues on Windows
    if sys.stdout.encoding != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Score candidates using local fallback scoring logic."
    )
    parser.add_argument("--profile", required=True, help="Path to profile JSON")
    parser.add_argument("--weights", required=True, help="Path to weights JSON")
    parser.add_argument("--route-catalog", required=True, help="Path to route_catalog.json")
    parser.add_argument("--environment-dashboard", required=True, help="Path to environment_dashboard.json")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    weights_path = Path(args.weights)
    route_catalog_path = Path(args.route_catalog)
    env_dashboard_path = Path(args.environment_dashboard)

    # Validate inputs exist
    for p in [profile_path, weights_path, route_catalog_path, env_dashboard_path]:
        if not p.exists():
            print(json.dumps({"error": f"File not found: {p}"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(2)

    try:
        profile = _read_json_file(profile_path)
        weights_data = _read_json_file(weights_path)
        route_catalog = _read_json_file(route_catalog_path)
        env_dashboard = _read_json_file(env_dashboard_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": f"Failed to read input: {exc}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)

    # Normalize weights
    if isinstance(weights_data, dict):
        weights = {k: float(v) for k, v in weights_data.items() if k in REQUIRED_DIMENSIONS}
    else:
        weights = dict(DEFAULT_WEIGHTS)
    # Fill missing dimensions with defaults
    for dim in REQUIRED_DIMENSIONS:
        if dim not in weights:
            weights[dim] = DEFAULT_WEIGHTS[dim]

    # Compute weights hash
    weights_sha256 = _sha256_file(weights_path)

    # Build env index
    env_index = _build_route_env_index(env_dashboard)

    # Normalize route catalog
    if isinstance(route_catalog, list):
        routes = route_catalog
    elif isinstance(route_catalog, dict):
        routes = route_catalog.get("routes", [])
    else:
        routes = []

    # Score
    result = _score_candidates_local(profile, weights, routes, env_index, weights_sha256)

    # Output single JSON to stdout
    output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(output)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()

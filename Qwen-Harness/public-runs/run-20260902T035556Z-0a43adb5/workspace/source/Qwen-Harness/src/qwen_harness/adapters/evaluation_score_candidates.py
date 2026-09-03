"""Evaluation score-candidates adapter.

Narrow bridge that imports and calls evaluation_model_qwen.service.score_candidates
and emits the resulting Pydantic model as a single UTF-8 JSON object on stdout.

Usage (standalone):
    python evaluation_score_candidates.py \
        --profile <path> --weights <path> \
        --route-catalog <path> --environment-dashboard <path>

No local scoring logic, no subprocess delegation, no external-project imports.
The generated evaluation_model_qwen package is the sole business implementation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_DIMENSIONS = frozenset(
    {
        "environment_health",
        "sport_match",
        "access_convenience",
        "route_quality",
        "interest_service",
    }
)


def _fail(msg: str) -> None:
    """Write error to stderr and exit with code 2."""
    print(f"[evaluation_score_candidates] ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def _validate_result(payload: dict[str, Any]) -> None:
    """Validate candidate_count, candidates length, and five-dimension scores."""
    candidate_count = payload.get("candidate_count")
    candidates = payload.get("candidates")

    if candidate_count is None:
        _fail("Missing field: candidate_count")
    if candidates is None:
        _fail("Missing field: candidates")
    if not isinstance(candidates, list):
        _fail("Field 'candidates' must be a list")
    if not isinstance(candidate_count, int):
        _fail("Field 'candidate_count' must be an integer")
    if candidate_count != len(candidates):
        _fail(
            f"candidate_count ({candidate_count}) != len(candidates) ({len(candidates)})"
        )

    for idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            _fail(f"candidates[{idx}] is not an object")
        if "route_id" not in cand:
            _fail(f"candidates[{idx}] missing route_id")

        # Accept either 'scores' or 'dimension_scores' key.
        scores = cand.get("scores") or cand.get("dimension_scores")
        if scores is None:
            _fail(
                f"candidates[{idx}] (route_id={cand.get('route_id')}) "
                f"missing 'scores' or 'dimension_scores'"
            )
        if not isinstance(scores, dict):
            _fail(
                f"candidates[{idx}] (route_id={cand.get('route_id')}) "
                f"scores must be a dict"
            )

        missing_dims = REQUIRED_DIMENSIONS - set(scores.keys())
        if missing_dims:
            _fail(
                f"candidates[{idx}] (route_id={cand.get('route_id')}) "
                f"missing dimensions: {sorted(missing_dims)}"
            )

        for dim in REQUIRED_DIMENSIONS:
            val = scores[dim]
            if not isinstance(val, (int, float)):
                _fail(
                    f"candidates[{idx}] (route_id={cand.get('route_id')}) "
                    f"dimension '{dim}' is not numeric: {val!r}"
                )
            if val < 0 or val > 100:
                _fail(
                    f"candidates[{idx}] (route_id={cand.get('route_id')}) "
                    f"dimension '{dim}' out of [0,100]: {val}"
                )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Score candidates via evaluation_model_qwen service."
    )
    parser.add_argument("--profile", required=True, help="Path to user profile JSON")
    parser.add_argument("--weights", required=True, help="Path to weights JSON")
    parser.add_argument(
        "--route-catalog", required=True, help="Path to route_catalog.json"
    )
    parser.add_argument(
        "--environment-dashboard",
        required=True,
        help="Path to environment_dashboard.json",
    )
    args = parser.parse_args(argv)

    profile_path = Path(args.profile)
    weights_path = Path(args.weights)
    route_catalog_path = Path(args.route_catalog)
    environment_dashboard_path = Path(args.environment_dashboard)

    for label, p in [
        ("profile", profile_path),
        ("weights", weights_path),
        ("route-catalog", route_catalog_path),
        ("environment-dashboard", environment_dashboard_path),
    ]:
        if not p.is_file():
            _fail(f"Input file for --{label} not found: {p}")

    # Import the generated evaluation service – the sole scoring implementation.
    try:
        from evaluation_model_qwen.service import score_candidates  # type: ignore[import-untyped]
    except ImportError as exc:
        _fail(
            f"Cannot import evaluation_model_qwen.service.score_candidates: {exc}. "
            "Ensure the evaluation_model_qwen package is installed in the active environment."
        )

    try:
        result_model = score_candidates(
            profile_path=str(profile_path),
            weights_path=str(weights_path),
            route_catalog_path=str(route_catalog_path),
            environment_dashboard_path=str(environment_dashboard_path),
        )
    except Exception as exc:
        _fail(f"score_candidates raised: {exc}")

    # Serialize the Pydantic model to a JSON-compatible dict.
    try:
        payload: dict[str, Any] = result_model.model_dump(mode="json")
    except Exception as exc:
        _fail(f"model_dump failed: {exc}")

    # Validate the contract before emitting.
    _validate_result(payload)

    # Emit single UTF-8 JSON object to stdout.
    try:
        out = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    except Exception as exc:
        _fail(f"Failed to write JSON to stdout: {exc}")


if __name__ == "__main__":
    main()

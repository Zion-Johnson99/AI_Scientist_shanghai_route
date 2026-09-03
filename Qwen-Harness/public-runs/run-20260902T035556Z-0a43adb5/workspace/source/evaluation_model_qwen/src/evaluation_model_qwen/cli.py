"""CLI entry point for evaluation_model_qwen.

Subcommands:
  api-check        Check API service reachability.
  recommend        Run full recommendation pipeline.
  score-candidates Export scored candidates for experiment engine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from evaluation_model_qwen.models import (
    CandidateScoreResult,
    RiskAssessment,
    ScoredRoute,
    UserProfile,
)
from evaluation_model_qwen.loaders import load_data
from evaluation_model_qwen.scoring import evaluate_risk, score_routes
from evaluation_model_qwen.service import evaluation_root, load_weights
from evaluation_model_qwen.constraints import apply_hard_constraints


@click.group()
def main() -> None:
    """Evaluation model for personalized health route recommendations."""


@main.command("api-check")
@click.option("--host", default="127.0.0.1", help="API host.")
@click.option("--port", default=8000, type=int, help="API port.")
@click.option("--timeout", default=5.0, type=float, help="Request timeout seconds.")
def api_check(host: str, port: int, timeout: float) -> None:
    """Check API service reachability."""
    import httpx

    url = f"http://{host}:{port}/api/v1/health"
    try:
        resp = httpx.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            click.echo(json.dumps({"status": "ok", "detail": data}, ensure_ascii=False))
            sys.exit(0)
        else:
            click.echo(
                json.dumps(
                    {"status": "error", "detail": f"HTTP {resp.status_code}"},
                    ensure_ascii=False,
                ),
                err=True,
            )
            sys.exit(1)
    except httpx.ConnectError:
        click.echo(
            json.dumps(
                {"status": "error", "detail": f"Cannot connect to {url}"},
                ensure_ascii=False,
            ),
            err=True,
        )
        sys.exit(1)
    except Exception as exc:
        click.echo(
            json.dumps(
                {"status": "error", "detail": str(exc)},
                ensure_ascii=False,
            ),
            err=True,
        )
        sys.exit(1)


@main.command("recommend")
@click.option("--profile", "profile_path", required=True, type=click.Path(exists=True), help="User profile JSON file.")
@click.option("--weights", "weights_path", default=None, type=click.Path(exists=True), help="Weights JSON file (default: config/default_weights.json).")
@click.option("--route-catalog", "route_catalog_path", default=None, type=click.Path(exists=True), help="Route catalog JSON path.")
@click.option("--environment-dashboard", "env_dashboard_path", default=None, type=click.Path(exists=True), help="Environment dashboard JSON path.")
@click.option("--offline", is_flag=True, default=False, help="Run without Qwen API calls.")
@click.option("--json", "output_json", is_flag=True, default=False, help="Output as JSON.")
def recommend(
    profile_path: str,
    weights_path: Optional[str],
    route_catalog_path: Optional[str],
    env_dashboard_path: Optional[str],
    offline: bool,
    output_json: bool,
) -> None:
    """Run full recommendation pipeline."""
    try:
        profile = UserProfile.model_validate_json(Path(profile_path).read_text(encoding="utf-8"))
    except Exception as exc:
        click.echo(json.dumps({"error_type": "input_error", "message": f"Invalid profile: {exc}"}, ensure_ascii=False), err=True)
        sys.exit(2)

    root = evaluation_root()

    if weights_path is None:
        weights_path = str(root / "config" / "default_weights.json")
    weights = load_weights(Path(weights_path))

    if route_catalog_path is None:
        route_catalog_path = str(root.parent / "xuhui_route_builder" / "data" / "web" / "route_catalog.json")
    if env_dashboard_path is None:
        env_dashboard_path = str(root.parent / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json")

    try:
        routes, env_data = load_data(Path(route_catalog_path), Path(env_dashboard_path))
    except Exception as exc:
        click.echo(json.dumps({"error_type": "data_error", "message": str(exc)}, ensure_ascii=False), err=True)
        sys.exit(2)

    risk = evaluate_risk(env_data)

    if risk.pause:
        result = {
            "status": "paused",
            "reason": risk.pause_reason,
            "risk": risk.model_dump(),
            "recommendations": [],
        }
        if output_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"推荐暂停: {risk.pause_reason}")
        sys.exit(0)

    feasible = apply_hard_constraints(routes, profile, env_data)

    if not feasible:
        result = {
            "status": "no_candidates",
            "risk": risk.model_dump(),
            "recommendations": [],
            "message": "没有路线通过硬约束筛选",
        }
        if output_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo("没有路线通过硬约束筛选")
        sys.exit(0)

    scored = score_routes(feasible, profile, weights, env_data)

    if not offline:
        try:
            from evaluation_model_qwen.qwen_client import qwen_review
            scored = qwen_review(scored, profile)
        except Exception as exc:
            click.echo(f"[WARN] Qwen 服务异常，回退本地排序: {exc}", err=True)

    scored_sorted = sorted(scored, key=lambda r: r.base_score, reverse=True)

    result = {
        "status": "ok",
        "risk": risk.model_dump(),
        "candidate_count": len(scored_sorted),
        "recommendations": [
            {
                "route_id": s.route_id,
                "route_name": s.route_name,
                "base_score": s.base_score,
                "dimensions": s.dimensions,
            }
            for s in scored_sorted[:5]
        ],
    }

    if output_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"推荐 {len(scored_sorted)} 条候选路线（前 5）:")
        for i, rec in enumerate(result["recommendations"], 1):
            click.echo(f"  {i}. {rec['route_name']} (score={rec['base_score']:.3f})")


@main.command("score-candidates")
@click.option("--profile", "profile_path", required=True, type=click.Path(exists=True), help="User profile JSON file.")
@click.option("--weights", "weights_path", required=True, type=click.Path(exists=True), help="Weights JSON file.")
@click.option("--route-catalog", "route_catalog_path", required=True, type=click.Path(exists=True), help="Route catalog JSON path.")
@click.option("--environment-dashboard", "env_dashboard_path", required=True, type=click.Path(exists=True), help="Environment dashboard JSON path.")
@click.option("--json", "output_json", is_flag=True, default=True, help="Output as JSON (default).")
def score_candidates(
    profile_path: str,
    weights_path: str,
    route_catalog_path: str,
    env_dashboard_path: str,
    output_json: bool,
) -> None:
    """Export scored candidates for experiment engine.

    Returns all candidates passing hard constraints with dimension scores.
    Does not call Qwen. Does not modify recommend behavior.
    """
    import hashlib

    try:
        profile = UserProfile.model_validate_json(Path(profile_path).read_text(encoding="utf-8"))
    except Exception as exc:
        click.echo(
            json.dumps({"error_type": "input_error", "message": f"Invalid profile: {exc}"}, ensure_ascii=False),
            err=True,
        )
        sys.exit(2)

    weights_file = Path(weights_path)
    try:
        weights = load_weights(weights_file)
    except Exception as exc:
        click.echo(
            json.dumps({"error_type": "input_error", "message": f"Invalid weights: {exc}"}, ensure_ascii=False),
            err=True,
        )
        sys.exit(2)

    weights_sha256 = hashlib.sha256(weights_file.read_bytes()).hexdigest()

    try:
        routes, env_data = load_data(Path(route_catalog_path), Path(env_dashboard_path))
    except Exception as exc:
        click.echo(
            json.dumps({"error_type": "data_error", "message": str(exc)}, ensure_ascii=False),
            err=True,
        )
        sys.exit(2)

    risk = evaluate_risk(env_data)

    if risk.pause:
        result = CandidateScoreResult(
            profile=profile.model_dump(),
            risk=risk.model_dump(),
            data_generated_at=env_data.get("metadata", {}).get("generated_at", ""),
            candidate_count=0,
            candidates=[],
            weights_sha256=weights_sha256,
        )
        click.echo(result.model_dump_json(indent=2))
        sys.exit(0)

    feasible = apply_hard_constraints(routes, profile, env_data)

    if not feasible:
        result = CandidateScoreResult(
            profile=profile.model_dump(),
            risk=risk.model_dump(),
            data_generated_at=env_data.get("metadata", {}).get("generated_at", ""),
            candidate_count=0,
            candidates=[],
            weights_sha256=weights_sha256,
        )
        click.echo(result.model_dump_json(indent=2))
        sys.exit(0)

    scored = score_routes(feasible, profile, weights, env_data)
    scored_sorted = sorted(scored, key=lambda r: r.base_score, reverse=True)

    candidates = []
    for s in scored_sorted:
        candidates.append({
            "route_id": s.route_id,
            "route_name": s.route_name,
            "route_mode": s.route_mode,
            "base_score": s.base_score,
            "dimensions": s.dimensions,
        })

    result = CandidateScoreResult(
        profile=profile.model_dump(),
        risk=risk.model_dump(),
        data_generated_at=env_data.get("metadata", {}).get("generated_at", ""),
        candidate_count=len(candidates),
        candidates=candidates,
        weights_sha256=weights_sha256,
    )

    click.echo(result.model_dump_json(indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()

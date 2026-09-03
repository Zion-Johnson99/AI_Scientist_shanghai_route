"""Offline reproduction of the harness research stages for this run.

Reads only the artifacts already written inside this run directory and replays
the stage chain deterministically. It never constructs a model client and never
performs a network call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

COPY_ROOT: Path = Path(__file__).resolve().parent
RUN_ROOT: Path = COPY_ROOT.parent.parent
STAGES: tuple[str, ...] = (
    "initialize",
    "problem_framing",
    "source_collection",
    "evidence_extraction",
    "citation_validation",
    "gap_analysis",
    "hypothesis_generation",
    "hypothesis_critique",
    "hypothesis_selection",
    "experiment_design",
    "project_generation",
    "module_preflight",
    "module_execution",
    "experiment_analysis",
    "feedback_decision",
    "scientific_report",
    "web_payload",
    "final_validation",
    "publish_web",
)
STAGE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "initialize": ("run_manifest.json", "provider_manifest.json"),
    "problem_framing": ("experiments/research_goal.json",),
    "source_collection": ("sources/source_registry.jsonl",),
    "evidence_extraction": ("experiments/evidence_cards.jsonl",),
    "citation_validation": ("sources/source_registry.jsonl",),
    "gap_analysis": ("experiments/knowledge_gaps.json",),
    "hypothesis_generation": ("experiments/hypotheses.json",),
    "hypothesis_critique": ("experiments/hypothesis_critique.json",),
    "hypothesis_selection": ("experiments/hypotheses.json",),
    "experiment_design": (
        "experiments/experiment_design.json",
        "experiments/baseline_design.json",
        "experiments/evaluation_metrics.json",
        "experiments/stop_conditions.json",
    ),
    "project_generation": ("workspace/source/pyproject.toml",),
    "module_preflight": ("workspace/source/xuhui_route_builder/route_builder.py",),
    "module_execution": ("workspace/source/xuhui_route_builder/data/web/route_catalog.json",),
    "experiment_analysis": ("experiments/scientific_plan.json",),
    "feedback_decision": ("experiments/stop_conditions.json",),
    "scientific_report": ("reports/科学计划.md",),
    "web_payload": ("publish/research_harness_latest.json",),
    "final_validation": ("checks/generated_quality.json",),
    "publish_web": ("publish/local-product/index.html",),
}


def read_json(path: Path) -> Any:
    """Read a JSON file, returning None when it is absent."""
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay() -> dict[str, Any]:
    """Report which stage artifacts are present and hash them."""
    records: list[dict[str, Any]] = []
    for stage in STAGES:
        artifacts = []
        for relative in STAGE_ARTIFACTS.get(stage, ()):
            target = RUN_ROOT / relative
            artifacts.append(
                {
                    "path": relative,
                    "present": target.is_file(),
                    "bytes": target.stat().st_size if target.is_file() else 0,
                    "sha256": sha256_of(target) if target.is_file() else None,
                }
            )
        complete = bool(artifacts) and all(item["present"] for item in artifacts)
        records.append(
            {
                "stage": stage,
                "status": "passed" if complete else ("pending" if artifacts else "no_artifact"),
                "artifacts": artifacts,
            }
        )
    passed = sum(1 for r in records if r["status"] == "passed")
    return {
        "run_id": RUN_ROOT.name,
        "stage_count": len(STAGES),
        "passed": passed,
        "pending": sum(1 for r in records if r["status"] == "pending"),
        "stages": records,
        "offline": True,
        "provider": "qoder_session",
        "model_name": "qwen3.8-max",
        "dashscope_api_used": False,
    }


def main() -> int:
    """Print the replay summary and optionally write it to a file."""
    parser = argparse.ArgumentParser(description="Replay harness stages offline.")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    summary = replay()
    sys.stdout.write(
        f"[harness-copy] stages={summary['stage_count']} "
        f"passed={summary['passed']} pending={summary['pending']}\n"
    )
    for record in summary["stages"]:
        sys.stdout.write(f"  {record['stage']:<22} {record['status']}\n")
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Harness 内部候选评分入口。

该入口由 :class:`EvaluationModelAdapter` 在评分模块自身的 Python
环境中执行，复用模块现有的数据加载、风险判定与路线评分函数。
评分模块无需为 Harness 增加 CLI 子命令。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_CHUNK_SIZE = 65536
_SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


class CandidateExportResult(BaseModel):
    """Harness 实验层使用的全部可行候选契约。"""

    model_config = ConfigDict(extra="forbid")

    profile: dict[str, Any]
    risk: dict[str, Any]
    data_generated_at: datetime
    candidate_count: int = Field(ge=0)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    weights_sha256: str

    @model_validator(mode="after")
    def _check_count(self) -> "CandidateExportResult":
        if self.candidate_count != len(self.candidates):
            raise ValueError(
                f"candidate_count={self.candidate_count} 与 "
                f"len(candidates)={len(self.candidates)} 不一致"
            )
        return self


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen-Harness 候选路线评分导出")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--route-catalog", type=Path, required=True)
    parser.add_argument("--environment-dashboard", type=Path, required=True)
    return parser


def _weights_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _load_evaluation_api() -> SimpleNamespace:
    """仅在执行评分时加载当前 run 生成的评价模块。"""
    try:
        loaders = import_module("evaluation_model_qwen.loaders")
        models = import_module("evaluation_model_qwen.models")
        scoring = import_module("evaluation_model_qwen.scoring")
        service = import_module("evaluation_model_qwen.service")
        return SimpleNamespace(
            load_data=loaders.load_data,
            UserProfile=models.UserProfile,
            evaluate_risk=scoring.evaluate_risk,
            score_routes=scoring.score_routes,
            evaluation_root=service.evaluation_root,
            load_weights=service.load_weights,
        )
    except (AttributeError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "当前 run 生成的评价模块缺少 loaders/models/scoring/service 契约"
        ) from exc


def _dump_model(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        document = dump(mode="json")
        if isinstance(document, dict):
            return document
    raise TypeError(f"{label} 需为 Pydantic 模型或字典")


def score_candidates(
    profile: Any,
    *,
    route_catalog_path: Path,
    environment_path: Path,
    weights_path: Path,
) -> CandidateExportResult:
    """执行硬约束过滤与五维评分，导出全部可行候选。"""
    api = _load_evaluation_api()
    weights = api.load_weights(weights_path)
    bundle = api.load_data(
        project_root=api.evaluation_root(),
        route_catalog_path=route_catalog_path,
        environment_path=environment_path,
    )
    risk = api.evaluate_risk(bundle, profile, weights)
    risk_dump = _dump_model(risk, label="risk")
    candidates = (
        []
        if risk_dump.get("status") == "paused"
        else api.score_routes(bundle, profile, risk, weights)
    )
    candidate_dumps = [_dump_model(candidate, label="candidate") for candidate in candidates]
    profile_dump = _dump_model(profile, label="profile")
    if profile_dump.get("free_text"):
        profile_dump["free_text"] = "[已省略]"
    return CandidateExportResult(
        profile=profile_dump,
        risk=risk_dump,
        data_generated_at=bundle.environment.generated_at,
        candidate_count=len(candidate_dumps),
        candidates=candidate_dumps,
        weights_sha256=_weights_sha256(weights_path),
    )


def _load_profile(path: Path) -> Any:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"用户画像读取失败: path={path}, error={exc}") from exc
    if not isinstance(document, dict):
        raise TypeError(f"用户画像顶层需为对象: path={path}")
    if document.get("target_time") == "now":
        document["target_time"] = datetime.now(_SHANGHAI_TZ).isoformat()
    return _load_evaluation_api().UserProfile.model_validate(document)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = score_candidates(
            _load_profile(args.profile),
            route_catalog_path=args.route_catalog,
            environment_path=args.environment_dashboard,
            weights_path=args.weights,
        )
    except (OSError, RuntimeError, TypeError, ValueError, ValidationError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CandidateExportResult", "build_parser", "main", "score_candidates"]

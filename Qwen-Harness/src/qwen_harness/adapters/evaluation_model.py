"""EvaluationModelAdapter：Harness 内部候选评分窄接口（设计文档 01 §15.4）。

通过 Harness 自有脚本复用评分模块现有的加载与评分函数，获取全部通过
硬约束的可行候选。脚本在当前 run 生成评分模块的环境中
执行，因此评分模块无需增加 Harness 专用 CLI。
输出契约::

    {"profile": {}, "risk": {}, "data_generated_at": "...",
     "candidate_count": 0, "candidates": [], "weights_sha256": "..."}

校验后的完整结果写入运行目录 ``modules/evaluation/``。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..experiments.metrics import DIMENSION_NAMES
from ..experiments.runner import CELLS_DIR
from ..experiments.variants import VARIANT_IDS
from ..models import ExperimentPlan
from .base import ModuleAdapter

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..models import ModuleOperation
    from ..workflow.engine import WorkflowContext

INTERNAL_SCORE_SCRIPT = "src/qwen_harness/adapters/evaluation_score_candidates.py"

#: 离线复现用固定示例数据（七、离线模式）。
#: 默认权重文件缺失时的确定性占位哈希（仅离线复现，标注来源）。
OFFLINE_WEIGHTS_FALLBACK_SHA = "offline-fixture-reproduction-no-default-weights-file"

#: score-candidates 输出契约必备键 -> 期望类型名（用于错误消息）。
_CONTRACT_FIELDS: dict[str, tuple[type | tuple[type, ...], str]] = {
    "profile": (dict, "对象"),
    "risk": (dict, "对象"),
    "data_generated_at": (str, "时间戳字符串"),
    "candidate_count": (int, "整数"),
    "candidates": (list, "数组"),
    "weights_sha256": (str, "字符串"),
}


class EvaluationModelAdapter(ModuleAdapter):
    """评分模块 Adapter：仅通过 score-candidates 窄接口取候选。"""

    module = "evaluation"
    supported_operations = ("evaluation.score_candidates",)

    # -- 预检与快照 -------------------------------------------------------------
    def preflight(self, context: "WorkflowContext") -> Any:
        errors: list[str] = []
        paths = self.project_paths(context)
        module_dir = paths.evaluation_module
        if not module_dir.is_dir():
            errors.append(f"评分模块目录缺失: {self.repo_relative(context, module_dir)}")
        score_script = paths.resolve_path(
            paths.harness_root / INTERNAL_SCORE_SCRIPT, "Harness 候选评分脚本"
        )
        if not score_script.is_file():
            errors.append("当前 run 生成源码缺少 Harness 候选评分脚本")
        weights = self._default_weights(context)
        if weights is None:
            errors.append(
                f"默认评分权重缺失: "
                f"{self.repo_relative(context, self._default_weights_path(context))}"
            )
        else:
            try:
                self.read_json(weights, "默认评分权重")
            except InputContractError as exc:
                errors.append(exc.message)
        for label, path in (
            ("路线目录", paths.route_catalog_path),
            ("环境仪表盘", paths.environment_dashboard_path),
        ):
            if not path.is_file():
                errors.append(f"score-candidates 输入缺失: {label}（{self.repo_relative(context, path)}）")
        if errors:
            return self.result("error", errors=errors)
        return self.result("ok")

    def snapshot(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        paths = []
        project_paths = self.project_paths(context)
        for label, path in (
            ("默认评分权重", self._default_weights_path(context)),
            ("路线目录", project_paths.route_catalog_path),
            ("环境仪表盘", project_paths.environment_dashboard_path),
        ):
            if path.is_file():
                paths.append(path)
            else:
                warnings.append(f"快照缺少文件: {label}")
        if not paths:
            return self.result("error", errors=["评分输入与权重全部缺失"], warnings=warnings)
        hashes = self.hash_files(paths)
        status = "ok" if not warnings else "partial"
        return self.result(
            status,
            input_artifacts=[self.repo_relative(context, path) for path in paths],
            data_hashes=hashes,
            warnings=warnings,
        )

    def validate(self, context: "WorkflowContext") -> Any:
        """校验 score-candidates 输出契约是否仍可实现（输入齐全即可）。"""
        preflight = self.preflight(context)
        if preflight.status == "error":
            return preflight
        weights = self._default_weights(context)
        warnings = list(preflight.warnings)
        if weights is not None:
            data = self.read_json(weights, "默认评分权重")
            for key in ("goal_weights", "environment_weights", "risk_thresholds", "status_reliability"):
                if key not in data:
                    warnings.append(f"默认权重缺少字段 {key}，score-candidates 可能失败")
        status = "partial" if warnings else "ok"
        return self.result(status, warnings=warnings)

    # -- 操作执行 ---------------------------------------------------------------
    def execute(self, operation: "ModuleOperation", context: "WorkflowContext") -> Any:
        op = operation.operation_id
        if op != "evaluation.score_candidates":
            return self.unknown_operation(operation)
        if not self.commands_allowed(context):
            return self._offline_fixture_cells(operation, context)

        errors: list[str] = []
        profile_path = self._resolve_profile(operation, context, errors)
        weights_path = self._resolve_weights(operation, context, errors)
        project_paths = self.project_paths(context)
        catalog = project_paths.route_catalog_path
        dashboard = project_paths.environment_dashboard_path
        if not catalog.is_file():
            errors.append(f"路线目录缺失: {self.repo_relative(context, catalog)}")
        if not dashboard.is_file():
            errors.append(f"环境仪表盘缺失: {self.repo_relative(context, dashboard)}")
        if errors or profile_path is None or weights_path is None:
            return self.result("error", errors=errors or ["score-candidates 输入解析失败"])

        audit = self.run_fixed_command(
            context,
            command_id=f"evaluation.score_candidates.{self.safe_label(operation.parameters.get('label'), 'run')}",
            argv=self._score_command_argv(
                context,
                profile_path=profile_path,
                weights_path=weights_path,
                catalog_path=catalog,
                dashboard_path=dashboard,
            ),
            cwd=project_paths.evaluation_module,
            timeout_seconds=1200,
        )

        payload, contract_errors = self._read_command_output(audit.stdout_path)
        if contract_errors:
            return self.result("error", commands=[audit], errors=contract_errors)
        if payload is None:
            return self.result("error", commands=[audit], errors=["score-candidates 输出为空"])
        output_artifacts = self._write_candidate_cells(operation, context, payload)
        return self.result(
            "ok",
            input_artifacts=[
                self.repo_relative(context, profile_path),
                self.repo_relative(context, weights_path),
                self.repo_relative(context, catalog),
                self.repo_relative(context, dashboard),
            ],
            output_artifacts=output_artifacts,
            data_hashes={"weights_sha256": str(payload["weights_sha256"])},
            commands=[audit],
            warnings=[
                f"候选数 {payload['candidate_count']}（风险状态 {payload['risk'].get('status', '未知')}）"
            ],
        )

    def _write_candidate_cells(
        self,
        operation: "ModuleOperation",
        context: "WorkflowContext",
        payload: dict[str, Any],
    ) -> list[str]:
        """将一次画像评分结果登记到每个预注册选择变体。"""
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        raw_case_id = str(
            operation.parameters.get("label") or profile.get("case_id") or "profile"
        ).strip()
        case_id = "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in raw_case_id
        )[:64] or "profile"
        requested = operation.parameters.get("variants")
        requested_set = (
            {str(item) for item in requested} if isinstance(requested, list) else set(VARIANT_IDS)
        )
        variants = [variant for variant in VARIANT_IDS if variant in requested_set]
        if not variants:
            raise InputContractError("评分操作没有可用的预注册变体")
        outputs: list[str] = []
        for variant_id in variants:
            relative = f"{CELLS_DIR}/{case_id}__{variant_id}.json"
            cell = dict(payload)
            cell.update({"case_id": case_id, "variant_id": variant_id})
            context.store.write_json_atomic(relative, cell)
            outputs.append(relative)
        return outputs

    # -- 离线复现 ---------------------------------------------------------------
    #: 离线复现的固定画像参数（确定性，标注来源为 fixture）。
    _OFFLINE_ACCESS_DISTANCE_M = 120.0
    _OFFLINE_SEARCH_RADIUS_M = 1500.0
    _OFFLINE_BASE_SCORE = 0.75
    _OFFLINE_DATA_CONFIDENCE = 0.8
    _OFFLINE_DIMENSION_SCORE = 0.7

    def _offline_fixture_cells(self, operation: "ModuleOperation", context: "WorkflowContext") -> Any:
        """离线复现：由固定示例数据确定性生成候选单元，不执行任何命令。

        数据来自当前 run 的生成路线目录与环境仪表盘，每个
        画像×case×变体写一个 ``experiments/score_candidates/{case}__{variant}.json``；
        全部结果标注 ``provenance=offline_fixtures``，仅用于无网络闭环复现。
        """
        try:
            plan = context.read_stage_output_model("experiment_design", ExperimentPlan)
        except InputContractError as exc:
            return self.result("error", errors=[f"离线复现读取实验计划失败: {exc}"])

        project_paths = self.project_paths(context)
        fixture_paths = [
            project_paths.route_catalog_path,
            project_paths.environment_dashboard_path,
        ]
        fixtures: dict[str, Any] = {}
        for label, path in (
            ("离线路线样例", project_paths.route_catalog_path),
            ("离线环境样例", project_paths.environment_dashboard_path),
        ):
            if not path.is_file():
                return self.result("error", errors=[f"{label}缺失: {path.name}"])
            try:
                fixtures[label] = self.read_json(path, label)
            except InputContractError as exc:
                return self.result("error", errors=[exc.message])

        weights = self._default_weights(context)
        if weights is not None:
            hashes = self.hash_files([weights])
            weights_sha256 = next(iter(hashes.values()), OFFLINE_WEIGHTS_FALLBACK_SHA)
        else:
            weights_sha256 = OFFLINE_WEIGHTS_FALLBACK_SHA

        catalog = fixtures["离线路线样例"]
        routes: dict[str, dict[str, Any]] = {
            str(row["route_id"]): row
            for row in (catalog if isinstance(catalog, list) else [])
            if isinstance(row, dict) and isinstance(row.get("route_id"), str)
        }
        dashboard = fixtures["离线环境样例"]
        dashboard_block = dashboard.get("routes") if isinstance(dashboard, dict) else None
        items = dashboard_block.get("items") if isinstance(dashboard_block, dict) else None
        env_by_route: dict[str, dict[str, Any]] = {
            str(item["route_id"]): item
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and isinstance(item.get("route_id"), str)
        }

        requested = operation.parameters.get("variants")
        requested_set = {str(item) for item in requested} if isinstance(requested, list) else set(VARIANT_IDS)
        variants = [variant_id for variant_id in VARIANT_IDS if variant_id in requested_set]
        if not variants:
            return self.result("error", errors=["离线复现未收到任何预注册变体参数"])

        generated_at = datetime.now(timezone.utc).isoformat()
        outputs: list[str] = []
        warnings: list[str] = []
        for profile in plan.profiles:
            if not isinstance(profile, dict):
                continue
            profile_id = str(profile.get("profile_id") or profile.get("id") or "profile")
            case_ids = [str(case) for case in (profile.get("case_ids") or []) if isinstance(case, str) and case]
            sensitivity = [str(item) for item in (profile.get("sensitivity") or []) if isinstance(item, str)]
            for case_id in case_ids:
                route = routes.get(case_id)
                if route is None:
                    warnings.append(f"离线样例未收录路线 {case_id}，该画像单元记为无候选")
                candidates = [self._offline_candidate(route, env_by_route.get(case_id, {}), sensitivity)] if route else []
                interests = list(dict.fromkeys(sensitivity + list(candidates[0]["matched_preferences"] if candidates else [])))
                cell = {
                    "variant_id": None,
                    "case_id": case_id,
                    "provenance": "offline_fixtures",
                    "data_generated_at": generated_at,
                    "candidate_count": len(candidates),
                    "weights_sha256": weights_sha256,
                    "profile": {
                        "case_id": case_id,
                        "profile_id": profile_id,
                        "mode": route.get("route_mode") if route else profile.get("mode"),
                        "target_distance_m": profile.get("target_distance_m"),
                        "distance_tolerance_ratio": plan.target_distance_tolerance,
                        "search_radius_m": self._OFFLINE_SEARCH_RADIUS_M,
                        "interests": interests,
                        "sensitivity": sensitivity,
                    },
                    "risk": {
                        "status": "ok",
                        "source": "offline_fixture",
                        "note": "离线复现固定风险状态：仅用于闭环演示，不代表真实风险判定",
                    },
                    "candidates": candidates,
                }
                for variant_id in variants:
                    cell_payload = dict(cell)
                    cell_payload["variant_id"] = variant_id
                    relative = f"{CELLS_DIR}/{case_id}__{variant_id}.json"
                    context.store.write_json_atomic(relative, cell_payload)
                    outputs.append(relative)

        return self.result(
            "ok",
            input_artifacts=[self.repo_relative(context, path) for path in fixture_paths],
            output_artifacts=outputs,
            data_hashes={"weights_sha256": weights_sha256},
            warnings=[
                *warnings,
                "离线复现模式：候选来自当前 run 的生成夹具（fixture/reproduction），"
                "未执行 score-candidates 命令，不代表真实评分输出"
            ],
        )

    def _offline_candidate(
        self, route: dict[str, Any], env_item: dict[str, Any], sensitivity: list[str]
    ) -> dict[str, Any]:
        """构造一个满足实验指标契约的离线候选（字段来源均为固定样例）。"""
        preference_hits = [
            str(item) for item in (route.get("preference_hits") or []) if isinstance(item, (str, int, float))
        ]
        summary = {
            "pm2_5": {"value": self._offline_summary_value(env_item.get("pm2_5"))},
            "noise": {"value": self._offline_summary_value(env_item.get("noise"))},
            "pollen": {"value": self._offline_pollen_value(env_item.get("pollen_daily"))},
        }
        return {
            "route": {
                "route_id": route.get("route_id"),
                "route_name": route.get("route_name") or "",
                "route_mode": route.get("route_mode"),
                "distance_m": route.get("distance_m"),
            },
            "access_distance_m": self._OFFLINE_ACCESS_DISTANCE_M,
            "base_score": self._OFFLINE_BASE_SCORE,
            "data_confidence": self._OFFLINE_DATA_CONFIDENCE,
            "matched_preferences": [hit for hit in preference_hits if hit in set(sensitivity)],
            "dimension_scores": {name: self._OFFLINE_DIMENSION_SCORE for name in DIMENSION_NAMES},
            "environment_summary": summary,
        }

    @staticmethod
    def _offline_summary_value(block: Any) -> float | None:
        if isinstance(block, dict):
            value = block.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None

    @staticmethod
    def _offline_pollen_value(pollen_daily: Any) -> float | None:
        if isinstance(pollen_daily, list) and pollen_daily:
            first = pollen_daily[0]
            if isinstance(first, dict):
                value = first.get("value")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
        return None

    # -- 参数解析 ----------------------------------------------------------------
    def _score_command_argv(
        self,
        context: "WorkflowContext",
        *,
        profile_path: Path,
        weights_path: Path,
        catalog_path: Path,
        dashboard_path: Path,
    ) -> list[str]:
        """构建 Harness 内部评分脚本命令，运行环境由目标评分模块提供。"""
        paths = self.project_paths(context)
        script_path = paths.resolve_path(
            paths.harness_root / INTERNAL_SCORE_SCRIPT, "Harness 候选评分脚本"
        )
        return [
            "uv",
            "run",
            "--directory",
            str(paths.evaluation_module),
            "python",
            str(script_path),
            "--profile",
            str(profile_path),
            "--weights",
            str(weights_path),
            "--route-catalog",
            str(catalog_path),
            "--environment-dashboard",
            str(dashboard_path),
        ]

    def _resolve_profile(
        self, operation: "ModuleOperation", context: "WorkflowContext", errors: list[str]
    ) -> Path | None:
        raw = operation.parameters.get("profile")
        if isinstance(raw, dict):
            relative = f"modules/evaluation/{self.safe_label(operation.parameters.get('label'), 'profile')}_input.json"
            context.store.write_json_atomic(relative, raw)
            return context.store.run_dir / relative
        if isinstance(raw, str) and raw.strip():
            project_paths = self.project_paths(context)
            path = project_paths.resolve_path(project_paths.source_root / raw, "profile 参数")
            if not path.is_file():
                errors.append(f"profile 文件不存在: {raw}")
                return None
            return path
        errors.append("操作参数缺少 profile（文件路径或内联对象）")
        return None

    def _resolve_weights(
        self, operation: "ModuleOperation", context: "WorkflowContext", errors: list[str]
    ) -> Path | None:
        raw = operation.parameters.get("weights")
        if raw is None:
            path = self._default_weights(context)
            if path is None:
                errors.append(
                    f"默认评分权重缺失: "
                    f"{self.repo_relative(context, self._default_weights_path(context))}"
                )
            return path
        if isinstance(raw, str) and raw.strip():
            project_paths = self.project_paths(context)
            path = project_paths.resolve_path(project_paths.source_root / raw, "weights 参数")
            if not path.is_file():
                errors.append(f"weights 文件不存在: {raw}")
                return None
            return path
        errors.append("weights 参数必须是仓库相对路径字符串")
        return None

    def _default_weights_path(self, context: "WorkflowContext") -> Path:
        paths = self.project_paths(context)
        return paths.resolve_path(
            paths.evaluation_module / "config" / "default_weights.json", "默认评分权重"
        )

    def _default_weights(self, context: "WorkflowContext") -> Path | None:
        path = self._default_weights_path(context)
        return path if path.is_file() else None

    # -- 输出契约校验 ---------------------------------------------------------
    def _read_command_output(self, stdout_path: str) -> tuple[dict[str, Any] | None, list[str]]:
        path = Path(stdout_path)
        if not path.is_file():
            return None, [f"score-candidates 标准输出日志缺失: {stdout_path}"]
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return None, [f"score-candidates 输出无法读取: {exc}"]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, [f"score-candidates 输出不是合法 JSON: {exc}"]
        if not isinstance(payload, dict):
            return None, ["score-candidates 输出顶层必须是对象"]
        return payload, self._validate_contract(payload)

    def _validate_contract(self, payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for key, (expected, label) in _CONTRACT_FIELDS.items():
            if key not in payload:
                errors.append(f"score-candidates 输出缺少字段 {key}")
            elif not isinstance(payload[key], expected) or isinstance(payload[key], bool):
                errors.append(f"score-candidates 字段 {key} 应为{label}")
        if errors:
            return errors
        if isinstance(payload["candidate_count"], bool) or payload["candidate_count"] != len(
            payload["candidates"]
        ):
            errors.append(
                f"candidate_count={payload['candidate_count']!r} 与 candidates 数量 "
                f"{len(payload['candidates'])} 不一致"
            )
        if not str(payload["weights_sha256"]).strip():
            errors.append("weights_sha256 不能为空")
        return errors

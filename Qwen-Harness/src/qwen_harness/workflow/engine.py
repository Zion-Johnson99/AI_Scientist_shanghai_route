"""WorkflowEngine：确定性阶段编排（设计文档 01 §13、§17、§21）。

阶段处理器遵循冻结约定 ``def stage_handler(context: WorkflowContext) ->
StageResult``，在工作流 JSON 中以 ``"模块:函数"`` 引用，由
:class:`HandlerRegistry` 在执行时惰性解析。引擎的全部产物都经
:class:`RunStore` 写入 ``Qwen-Harness/runtime``，仅发布阶段可把产物
原子复制到网页数据目录。
"""

from __future__ import annotations

import importlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from .. import config as config_mod
from ..errors import HarnessError, InputContractError
from ..logging_utils import get_logger, setup_logging
from ..models import (
    ApprovalDecision,
    ApprovalGate,
    IterationDecision,
    ResearchGoal,
    ResumeOptions,
    RunContext,
    RunOptions,
    RunSummary,
    SourceRecord,
    StageResult,
    StageSpec,
    WorkflowConfig,
)
from ..paths import HarnessPaths
from ..run_store import RunStore
from ..skills import SkillRegistry
from .gates import build_gates
from .registry import HandlerRegistry, load_workflow
from .resume import plan_resume

logger = get_logger("workflow.engine")

MAX_RETRIES = 2
DEFAULT_STAGE_RETRIES = 2
RETRY_BACKOFF_SECONDS = (1.0, 2.0)
_DEFAULT_HARNESS_ROOT = Path(__file__).resolve().parents[3]

#: 离线模式下由 fixture 直接构造模型输出的阶段 -> models 类名。
#: 引擎原生阶段（initialize/module_*/final_validation/publish_web）不在此列。
OFFLINE_FIXTURE_MODELS: dict[str, str] = {
    "problem_framing": "ProblemFrame",
    "source_collection": "SourceRecord",
    "evidence_extraction": "EvidenceCard",
    "gap_analysis": "KnowledgeGapSet",
    "hypothesis_generation": "HypothesisSet",
    "hypothesis_critique": "HypothesisReview",
    "hypothesis_selection": "HypothesisReview",
    "experiment_design": "ExperimentPlan",
    "experiment_analysis": "ResultInterpretation",
    "feedback_decision": "IterationDecision",
    "scientific_report": "ScientificPlan",
    "web_payload": "WebPayload",
}

_DECISION_TO_CONCLUSION = {
    "stop_supported": "supported",
    "stop_partial": "partially_supported",
    "stop_unsupported": "unsupported",
    "stop_inconclusive": "inconclusive",
}

_FEEDBACK_ACTION_TARGETS = {
    "expand_sources": "source_collection",
    "refresh_environment": "module_execution",
    "rerun_profiles": "module_execution",
    "rerun_variant": "experiment_design",
    "adjust_registered_weights": "experiment_design",
    "tighten_detour_limit": "experiment_design",
    "relax_noncritical_filter": "experiment_design",
}

_STAGE_LABELS = {
    "initialize": "初始化",
    "problem_framing": "问题定义",
    "source_collection": "来源收集",
    "evidence_extraction": "证据抽取",
    "citation_validation": "引用验证",
    "gap_analysis": "缺口分析",
    "hypothesis_generation": "假设生成",
    "hypothesis_critique": "假设评审",
    "hypothesis_selection": "假设选择",
    "experiment_design": "实验设计",
    "project_generation": "千问生成完整工程",
    "module_preflight": "模块预检",
    "module_execution": "三模块执行",
    "experiment_analysis": "实验分析",
    "feedback_decision": "反馈决策",
    "scientific_report": "科研报告",
    "web_payload": "网页数据",
    "final_validation": "最终验证",
    "publish_web": "本地发布",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowContext:
    """传给每个阶段处理器的运行时上下文。"""

    def __init__(
        self,
        *,
        paths: HarnessPaths,
        settings: Any,
        harness_config: Any,
        workflow: WorkflowConfig,
        skills: SkillRegistry,
        store: RunStore,
        goal: ResearchGoal,
        options: RunOptions,
        state: Any,
        model_client: Any,
        prompts: Any,
        quality_gates: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.harness_config = harness_config
        self.workflow = workflow
        self.skills = skills
        self.store = store
        self.goal = goal
        self.options = options
        self.state = state
        self.model_client = model_client
        self.prompts = prompts
        self.quality_gates = quality_gates
        self.gates = build_gates(quality_gates)
        self.stage_spec: StageSpec | None = None
        self.conclusion_status: str | None = None
        self.audit_extras: dict[str, Any] = {}

    @property
    def run_store(self) -> RunStore:
        return self.store

    @property
    def run_id(self) -> str:
        return self.store.run_id

    @property
    def run_dir(self) -> Path:
        return self.store.run_dir

    @property
    def repo_root(self) -> Path:
        return self.paths.repo_root

    @property
    def harness_root(self) -> Path:
        return self.paths.harness_root

    @property
    def generated(self) -> SimpleNamespace:
        """当前 run 内由千问生成的模块路径契约。"""
        return SimpleNamespace(
            module_paths={
                "route": "xuhui_route_builder",
                "environment": "weather_api_data",
                "evaluation": "evaluation_model_qwen",
                "web": "xuhui_route_builder/web",
            }
        )

    @property
    def iteration(self) -> int:
        return self.state.iteration

    @property
    def offline(self) -> bool:
        return self.options.offline

    # -- 事件 -----------------------------------------------------------------
    def emit(
        self,
        event_type: str,
        message: str,
        *,
        status: str = "ok",
        details: dict[str, Any] | None = None,
    ) -> None:
        stage = self.stage_spec.name if self.stage_spec is not None else None
        self.store.emit(event_type, message, stage=stage, status=status, details=details)

    # -- 阶段产物 ---------------------------------------------------------------
    def read_stage_output(self, stage: str) -> dict[str, Any] | None:
        return self.store.read_stage_output(stage)

    def read_stage_output_model(self, stage: str, model: type) -> Any:
        data = self.store.read_stage_output(stage)
        if data is None:
            raise InputContractError(
                f"阶段 {stage} 尚无输出",
                stage=stage,
                run_id=self.run_id,
                suggested_action="先执行上游阶段",
            )
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise InputContractError(
                f"阶段 {stage} 输出不符合 {model.__name__} 契约: {exc}",
                stage=stage,
                run_id=self.run_id,
            ) from exc

    # -- 来源与证据 -----------------------------------------------------------
    def source_registry(self) -> dict[str, SourceRecord]:
        return self.store.load_source_registry()

    def append_source(self, record: SourceRecord) -> None:
        self.store.append_source_record(record)

    def append_evidence_card(self, card: Any) -> None:
        self.store.append_evidence_card(card)

    # -- 派生配置（仅反馈迭代写入，绝不覆盖仓库默认配置） -------------------
    def read_derived_config(self) -> dict[str, Any]:
        data = self.store.read_json("derived_config.json")
        return data if isinstance(data, dict) else {}

    def write_derived_config(self, patch: dict[str, Any], reason: str = "") -> dict[str, Any]:
        merged = {**self.read_derived_config(), **patch}
        self.store.write_json_atomic("derived_config.json", merged)
        self.emit(
            "derived_config_updated",
            reason or "派生配置更新",
            details={"patch_keys": sorted(patch)},
        )
        return merged


class WorkflowEngine:
    """按配置阶段序列执行：审批、重试、反馈迭代与质量门禁。"""

    def __init__(self, harness_root: str | Path | None = None) -> None:
        self.harness_root = Path(harness_root).resolve() if harness_root else _DEFAULT_HARNESS_ROOT
        self.settings = config_mod.load_settings(self.harness_root)
        self.harness_config = config_mod.load_harness_config(self.harness_root)
        self.paths = HarnessPaths.resolve(
            self.harness_root, self.harness_config, self.settings.runtime_root
        )
        self.registry = HandlerRegistry()
        self.skills = SkillRegistry(self.paths.repo_root)
        self.quality_gates = config_mod.load_quality_gates(self.harness_root)

    # -- 公共入口 ---------------------------------------------------------------
    def run(self, goal: ResearchGoal, options: RunOptions) -> RunSummary:
        workflow = load_workflow(self.paths.workflows_dir, options.workflow)
        setup_logging(self.paths.logs_dir)
        store = RunStore(self.paths, self.settings, self.harness_config)
        seed = store.create_run(
            goal, options, workflow=workflow, skills_hashes=self._skills_hashes(workflow)
        )
        store.acquire_lock()
        try:
            context = self._build_context(store, seed, workflow)
            self._set_run_status(context, "running")
            context.emit("run_started", f"运行 {context.run_id} 开始（workflow={workflow.name}）")
            self._print_run_started(context, resumed=False)
            return self._run_loop(context, 0)
        finally:
            store.release_lock()

    def resume(self, run_id: str, resume_options: ResumeOptions | None = None) -> RunSummary:
        setup_logging(self.paths.logs_dir)
        store = RunStore(self.paths, self.settings, self.harness_config)
        seed = store.load_run(run_id)
        workflow = load_workflow(self.paths.workflows_dir, seed.manifest.workflow_name)
        plan = plan_resume(store, seed, workflow, self.paths)
        options = seed.options
        if resume_options is not None and resume_options.publish_web:
            options = options.model_copy(update={"publish_web": True})
        store.acquire_lock()
        try:
            state = seed.state
            for name in plan.retryable:
                state.stage_statuses[name] = "pending"
            for item in plan.drift:
                state.drift_records.append({"drift": item, "recorded_at": _utc_now().isoformat()})
            store.save_state(state)
            context = self._build_context(store, seed, workflow, options_override=options)
            for item in plan.drift:
                context.emit("resume_drift", item, status="warning")
            for note in plan.notes:
                context.emit("resume_note", note)
            self._set_run_status(context, "running")
            context.emit("run_resumed", f"从阶段索引 {plan.start_index} 继续")
            self._print_run_started(context, resumed=True)
            return self._run_loop(context, plan.start_index)
        finally:
            store.release_lock()

    # -- 上下文构建 ---------------------------------------------------------
    def _build_context(
        self,
        store: RunStore,
        seed: RunContext,
        workflow: WorkflowConfig,
        options_override: RunOptions | None = None,
    ) -> WorkflowContext:
        return WorkflowContext(
            paths=self.paths,
            settings=self.settings,
            harness_config=self.harness_config,
            workflow=workflow,
            skills=self.skills,
            store=store,
            goal=seed.goal,
            options=options_override or seed.options,
            state=seed.state,
            model_client=self._build_model_client(seed.options),
            prompts=self._build_prompts(seed.options),
            quality_gates=self.quality_gates,
        )

    def _build_model_client(self, options: RunOptions) -> Any:
        if options.offline:
            return None
        try:
            module = importlib.import_module("qwen_harness.llm.client")
        except ModuleNotFoundError as exc:
            from ..errors import ModelUnavailableError

            raise ModelUnavailableError(
                "LLM 客户端模块尚未就绪（qwen_harness.llm.client 不存在）",
                suggested_action="使用 --offline 运行离线夹具，或等待科研智能层实现",
            ) from exc
        client_cls = getattr(module, "QwenModelClient", None)
        if client_cls is None:
            from ..errors import ModelUnavailableError

            raise ModelUnavailableError("qwen_harness.llm.client 缺少 QwenModelClient")
        factory = getattr(client_cls, "from_env", None)
        if callable(factory):
            try:
                return factory(self.settings, self.harness_config)
            except TypeError:
                return factory(self.settings)
        return client_cls(self.settings)

    def _build_prompts(self, _options: RunOptions) -> Any:
        try:
            module = importlib.import_module("qwen_harness.llm.prompts")
        except ModuleNotFoundError:
            return None
        builder_cls = getattr(module, "PromptBuilder", None)
        if builder_cls is None:
            return None
        for args in ((self.paths.harness_root / "prompts",), ()):
            try:
                return builder_cls(*args)
            except TypeError:
                continue
        return None

    def _skills_hashes(self, workflow: WorkflowConfig) -> dict[str, str]:
        required: list[str] = []
        for stage in workflow.stages:
            for name in stage.required_skills:
                if name not in required:
                    required.append(name)
        try:
            discovered = self.skills.discover()
        except Exception as exc:  # noqa: BLE001 - 技能缺失不阻塞建运行
            logger.warning("技能发现失败: %s", exc)
            return {}
        missing = [name for name in required if name not in discovered]
        if missing:
            logger.warning("工作流引用的技能缺失: %s", ", ".join(missing))
        return {name: discovered[name].sha256 for name in required if name in discovered}

    # -- 审批（§5.1 / §13）------------------------------------------------------
    def request_approval(self, gate: ApprovalGate, context: WorkflowContext) -> ApprovalDecision:
        stage = gate.stage
        spec = context.stage_spec
        options = context.options
        if spec is None or spec.approval == "none":
            return ApprovalDecision(
                approved=True, approver="policy", reason="阶段无需审批", decided_at=_utc_now()
            )
        consent = self._explicit_consent(stage, context)
        if options.approval_mode == "auto":
            return ApprovalDecision(
                approved=True,
                approver="auto",
                reason="approval-mode=auto 自动放行",
                decided_at=_utc_now(),
            )
        if consent and (spec.approval == "critical" or options.approval_mode == "all"):
            return ApprovalDecision(
                approved=True, approver="user", reason="已提供显式授权参数", decided_at=_utc_now()
            )
        if spec.approval == "critical" and options.approval_mode == "critical" and not consent:
            return ApprovalDecision(
                approved=False,
                approver="policy",
                reason="关键操作需要显式授权（如 --publish-web、--allow-network）",
                decided_at=_utc_now(),
            )
        if options.approval_mode == "all" and not consent:
            return ApprovalDecision(
                approved=False,
                approver="policy",
                reason="approval-mode=all 需要显式授权",
                decided_at=_utc_now(),
            )
        return ApprovalDecision(
            approved=True, approver="policy", reason="审批策略放行", decided_at=_utc_now()
        )

    def _explicit_consent(self, stage: str, context: WorkflowContext) -> bool:
        options = context.options
        if stage == "publish_web":
            return True
        if stage == "module_execution":
            return options.offline or options.refresh_environment == "none" or options.allow_network
        return True

    # -- 阶段执行 ------------------------------------------------------------
    def execute_stage(self, stage: StageSpec, context: WorkflowContext) -> StageResult:
        context.stage_spec = stage
        store = context.store
        state = context.state
        state.current_stage = stage.name
        store.save_state(state)
        input_payload = {
            "stage": stage.name,
            "iteration": state.iteration,
            "workflow": context.workflow.name,
            "offline": context.options.offline,
            "handler": stage.handler,
            "dependencies": {dep: store.stage_sha256(dep, "output") for dep in stage.dependencies},
            "prepared_at": _utc_now().isoformat(),
        }
        store.write_stage_input(stage.name, input_payload)
        input_sha = store.stage_sha256(stage.name, "input")
        if input_sha:
            state.stage_input_hashes[stage.name] = input_sha
            store.save_state(state)
        resolved = self._resolve_handler(stage)
        retries = min(
            stage.retry_limit if stage.retry_limit > 0 else DEFAULT_STAGE_RETRIES, MAX_RETRIES
        )
        attempt = 0
        while True:
            attempt += 1
            state.stage_statuses[stage.name] = "running"
            store.save_state(state)
            started = time.perf_counter()
            context.emit("stage_started", f"阶段 {stage.name} 开始（第 {attempt} 次）")
            self._print_stage_started(stage, context, attempt)
            result = self._invoke(stage, context, resolved)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            audit: dict[str, Any] = {
                "handler": stage.handler,
                "attempt": attempt,
                "retries_allowed": retries,
                "elapsed_ms": round(elapsed_ms, 1),
                "status": result.status,
                "summary": result.summary,
                "artifacts": list(result.artifacts),
                "offline": context.options.offline,
                "audited_at": _utc_now().isoformat(),
            }
            if result.gate_result is not None:
                audit["gate_result"] = result.gate_result.model_dump(mode="json")
            if context.audit_extras:
                audit.update(context.audit_extras)
                context.audit_extras.clear()
            store.write_stage_audit(stage.name, audit)
            if result.status == "retryable" and attempt <= retries:
                delay = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                context.emit(
                    "stage_retry",
                    f"阶段 {stage.name} 重试（{attempt}/{retries}），退避 {delay}s",
                    status="warning",
                )
                print(f"  [重试] {attempt}/{retries}，{delay:.1f} s 后继续", flush=True)
                time.sleep(delay)
                continue
            if result.status == "retryable":
                result = result.model_copy(update={"status": "failed"})
            if result.status in {"passed", "failed"}:
                store.write_stage_output(stage.name, dict(result.output))
            state.stage_statuses[stage.name] = result.status
            store.save_state(state)
            context.emit(
                "stage_finished",
                f"阶段 {stage.name} 结束: {result.status}",
                status=result.status,
                details={"elapsed_ms": round(elapsed_ms, 1), "summary": result.summary or ""},
            )
            self._refresh_full_run_report(context)
            self._print_stage_finished(stage, context, result, elapsed_ms)
            return result

    def _resolve_handler(self, stage: StageSpec) -> Any:
        """Resolve the stage handler; on failure return a failed StageResult."""
        try:
            return self.registry.resolve(stage.handler)
        except HarnessError as exc:
            return StageResult(
                stage=stage.name,
                status="failed",
                summary=exc.message,
                output={"error_type": exc.error_type, "error_message": exc.message},
                warnings=[exc.suggested_action] if exc.suggested_action else [],
                retryable=exc.retryable,
                exit_code=exc.exit_code,
            )
        except Exception as exc:  # noqa: BLE001 - 处理器解析保护
            return StageResult(
                stage=stage.name,
                status="failed",
                summary=f"处理器解析异常: {type(exc).__name__}: {exc}",
                output={"error_type": "input_contract_error", "error_message": str(exc)},
            )

    def _invoke(self, stage: StageSpec, context: WorkflowContext, resolved: Any) -> StageResult:
        if isinstance(resolved, StageResult):
            return resolved.model_copy(update={"stage": stage.name})
        handler = resolved
        if context.options.offline and stage.name in OFFLINE_FIXTURE_MODELS:
            fixture_result = self._offline_fixture_result(stage, context)
            if fixture_result is not None:
                return fixture_result
        try:
            result = handler(context)
        except HarnessError as exc:
            return StageResult(
                stage=stage.name,
                status="retryable" if exc.retryable else "failed",
                summary=exc.message,
                output={"error_type": exc.error_type, "error_message": exc.message},
                warnings=[exc.suggested_action],
                retryable=exc.retryable,
                exit_code=exc.exit_code,
            )
        except Exception as exc:  # noqa: BLE001 - 顶层阶段保护
            return StageResult(
                stage=stage.name,
                status="failed",
                summary=f"未处理异常: {type(exc).__name__}: {exc}",
                output={"error_type": type(exc).__name__, "error_message": str(exc)},
                warnings=["查看运行日志定位调用栈"],
            )
        if not isinstance(result, StageResult):
            return StageResult(
                stage=stage.name,
                status="failed",
                summary=f"阶段 {stage.name} 返回了非 StageResult 对象: {type(result).__name__}",
                output={"error_type": "input_contract_error", "error_message": "处理器契约违规"},
            )
        return result

    def _offline_fixture_result(
        self, stage: StageSpec, context: WorkflowContext
    ) -> StageResult | None:
        from .. import models

        path = (
            self.paths.harness_root
            / "examples"
            / "fixtures"
            / "model-responses"
            / f"{stage.name}.json"
        )
        if not path.is_file():
            logger.info("离线夹具缺失，回退到阶段处理器: %s", path)
            return None
        model_cls = getattr(models, OFFLINE_FIXTURE_MODELS[stage.name])
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return StageResult(
                stage=stage.name,
                status="failed",
                summary=f"离线夹具不可读: {path.name}: {exc}",
                output={"error_type": "input_contract_error", "error_message": str(exc)},
            )
        try:
            if isinstance(raw, list):
                validated = [model_cls.model_validate(item) for item in raw]
                payload: dict[str, Any] = {
                    "items": [item.model_dump(mode="json") for item in validated]
                }
            else:
                validated = model_cls.model_validate(raw)
                payload = validated.model_dump(mode="json")
        except ValidationError as exc:
            return StageResult(
                stage=stage.name,
                status="failed",
                summary=f"离线夹具不符合 {model_cls.__name__} 契约: {exc}",
                output={"error_type": "input_contract_error", "error_message": str(exc)},
            )
        context.audit_extras["fixture_source"] = path.relative_to(
            self.paths.harness_root
        ).as_posix()
        context.audit_extras["offline_fixture"] = True
        if stage.name == "source_collection" and isinstance(raw, list):
            for record in validated:  # type: ignore[union-attr]
                context.append_source(record)
        if stage.name == "evidence_extraction" and not isinstance(raw, list):
            # 离线短路绕过了 evidence_agent.stage_handler，需补上其 RunStore 副作用
            context.append_evidence_card(validated)
        if stage.name == "scientific_report":
            # 离线闭环：final_validation 需要 reports/scientific_plan.json 实物，
            # 不能只依赖 web_payload 阶段里被 try/except 吞掉的自愈路径。
            payload.update(
                {"run_id": context.run_id, "generated_at": datetime.now(timezone.utc).isoformat()}
            )
            context.store.write_json_atomic("reports/scientific_plan.json", payload)
            from ..reporting.full_run_report import write_full_run_report

            write_full_run_report(context)
        return StageResult(
            stage=stage.name,
            status="passed",
            summary=f"离线夹具输出（{path.name}）",
            output=payload,
            artifacts=["reports/full_run_report.md"] if stage.name == "scientific_report" else [],
        )

    # -- 主循环 -----------------------------------------------------------------
    def _run_loop(self, context: WorkflowContext, start_index: int) -> RunSummary:
        stages = context.workflow.stages
        store = context.store
        index = max(0, start_index)
        while index < len(stages):
            stage = stages[index]
            context.stage_spec = stage
            if not stage.enabled:
                context.state.stage_statuses[stage.name] = "skipped"
                store.save_state(context.state)
                context.emit("stage_skipped", f"阶段 {stage.name} 已禁用")
                self._print_stage_skipped(stage, context, "已禁用")
                index += 1
                continue
            decision = self.request_approval(
                ApprovalGate(
                    stage=stage.name,
                    level=stage.approval,
                    reason=f"阶段 {stage.name} 审批（handler={stage.handler}）",
                ),
                context,
            )
            store.write_json_atomic(
                f"stages/{stage.name}/approval.json", decision.model_dump(mode="json")
            )
            if not decision.approved:
                if stage.approval == "always":
                    context.state.stage_statuses[stage.name] = "skipped"
                    store.save_state(context.state)
                    context.emit(
                        "stage_skipped",
                        f"阶段 {stage.name} 未获显式授权: {decision.reason}",
                        status="warning",
                    )
                    self._print_stage_skipped(stage, context, decision.reason)
                    index += 1
                    continue
                context.state.stage_statuses[stage.name] = "needs_approval"
                self._set_run_status(context, "needs_approval")
                context.emit("approval_pending", decision.reason, status="warning")
                return self._summary(context)
            result = self.execute_stage(stage, context)
            if result.status == "failed":
                self._set_run_status(context, "failed")
                return self._summary(context)
            if stage.name == "feedback_decision" and result.status == "passed":
                jump = self._apply_feedback(context, stages)
                if jump is not None:
                    index = jump
                    continue
            index += 1
        self._set_run_status(context, "passed")
        return self._summary(context)

    def _set_run_status(self, context: WorkflowContext, status: str) -> None:
        state = context.state
        state.status = status  # type: ignore[assignment]
        if status in {"passed", "failed"}:
            state.finished_at = _utc_now()
        if context.conclusion_status is not None:
            state.final_support_status = context.conclusion_status  # type: ignore[assignment]
        context.store.save_state(state)
        self._refresh_full_run_report(context)
        if status in {"passed", "failed"}:
            self._refresh_local_publish_metadata(context)
        if status in {"passed", "failed", "needs_approval"}:
            elapsed = max(0.0, (_utc_now() - state.started_at).total_seconds())
            print(
                f"\n[运行] {status} · {elapsed:.2f} s\n  产物目录: {context.run_dir}",
                flush=True,
            )

    @staticmethod
    def _clean_summary(value: str | None, limit: int = 180) -> str:
        text = " ".join((value or "无额外摘要").split())
        return text if len(text) <= limit else f"{text[: limit - 1]}…"

    @staticmethod
    def _stage_position(stage: StageSpec, context: WorkflowContext) -> tuple[int, int]:
        names = [item.name for item in context.workflow.stages]
        return names.index(stage.name) + 1, len(names)

    def _print_run_started(self, context: WorkflowContext, *, resumed: bool) -> None:
        action = "继续" if resumed else "开始"
        print(
            f"\n[Harness] {action}运行 {context.run_id}\n"
            f"  工作流: {context.workflow.name}\n"
            f"  模式: {'offline fixture' if context.options.offline else '千问 API'}\n"
            f"  运行目录: {context.run_dir}",
            flush=True,
        )

    def _print_stage_started(
        self, stage: StageSpec, context: WorkflowContext, attempt: int
    ) -> None:
        position, total = self._stage_position(stage, context)
        label = _STAGE_LABELS.get(stage.name, stage.name)
        print(
            f"\n[{position:02d}/{total:02d}] {label} ({stage.name}) 开始 · 第 {attempt} 次",
            flush=True,
        )

    def _print_stage_finished(
        self,
        stage: StageSpec,
        context: WorkflowContext,
        result: StageResult,
        elapsed_ms: float,
    ) -> None:
        position, total = self._stage_position(stage, context)
        label = _STAGE_LABELS.get(stage.name, stage.name)
        artifact_text = "、".join(result.artifacts[:3]) or f"stages/{stage.name}/"
        print(
            f"[{position:02d}/{total:02d}] {label} {result.status} · {elapsed_ms / 1000:.2f} s\n"
            f"  摘要: {self._clean_summary(result.summary)}\n"
            f"  产物: {artifact_text}",
            flush=True,
        )

    def _print_stage_skipped(self, stage: StageSpec, context: WorkflowContext, reason: str) -> None:
        position, total = self._stage_position(stage, context)
        label = _STAGE_LABELS.get(stage.name, stage.name)
        print(
            f"\n[{position:02d}/{total:02d}] {label} skipped\n"
            f"  原因: {self._clean_summary(reason)}",
            flush=True,
        )

    @staticmethod
    def _refresh_full_run_report(context: WorkflowContext) -> None:
        report_path = context.run_dir / "reports" / "full_run_report.md"
        if not report_path.is_file():
            return
        try:
            from ..reporting.full_run_report import write_full_run_report

            write_full_run_report(context)
        except Exception:  # 报告刷新不覆盖业务阶段结果
            logger.exception("刷新完整运行报告失败: run_id=%s", context.run_id)

    @staticmethod
    def _refresh_local_publish_metadata(context: WorkflowContext) -> None:
        try:
            from ..reporting.local_publish import refresh_local_publish_metadata

            refresh_local_publish_metadata(context)
        except Exception:  # 交付包元数据刷新不覆盖已经完成的业务运行
            logger.exception("刷新本地交付包报告失败: run_id=%s", context.run_id)

    # -- 反馈迭代（§17）------------------------------------------------------
    def _apply_feedback(self, context: WorkflowContext, stages: list[StageSpec]) -> int | None:
        store = context.store
        names = [stage.name for stage in stages]
        data = context.read_stage_output("feedback_decision")
        if data is None:
            return None
        try:
            decision = IterationDecision.model_validate(data)
        except ValidationError as exc:
            logger.warning("feedback_decision 输出无效，停止迭代: %s", exc)
            return None
        iteration = context.state.iteration
        store.write_json_atomic(
            f"iterations/iteration-{iteration}/decision.json", decision.model_dump(mode="json")
        )
        if decision.status != "continue":
            context.conclusion_status = _DECISION_TO_CONCLUSION.get(decision.status)
            context.emit("iteration_stop", decision.reason, details={"status": decision.status})
            return None
        if iteration >= self._max_iterations(context):
            context.conclusion_status = "inconclusive"
            context.emit(
                "iteration_limit", "达到最大迭代次数，结果标记为 inconclusive", status="warning"
            )
            return None
        target = self._feedback_target(decision, names)
        if target is None:
            context.conclusion_status = "inconclusive"
            context.emit("iteration_stop", "反馈动作未给出有效回跳目标", status="warning")
            return None
        self._apply_automatic_actions(decision, context)
        self._archive_iteration_outputs(context, names[names.index(target) :])
        context.state.iteration += 1
        store.save_state(context.state)
        context.emit(
            "iteration_continue",
            f"进入第 {context.state.iteration} 轮迭代，回跳到 {target}",
            details={"goal": decision.next_iteration_goal or ""},
        )
        return names.index(target)

    def _max_iterations(self, context: WorkflowContext) -> int:
        candidates = [
            context.options.max_iterations,
            self.harness_config.runtime.max_iterations,
            self.settings.max_iterations,
        ]
        values = [value for value in candidates if isinstance(value, int) and value > 0]
        return min(values) if values else 2

    def _feedback_target(self, decision: IterationDecision, names: list[str]) -> str | None:
        available = set(names)
        for action in decision.automatic_actions:
            action_name = str(action.get("action", ""))
            explicit = action.get("target_stage")
            if (
                isinstance(explicit, str)
                and explicit in available
                and explicit in _FEEDBACK_ACTION_TARGETS.values()
            ):
                return explicit
            default = _FEEDBACK_ACTION_TARGETS.get(action_name)
            if default in available:
                return default
        return None

    def _apply_automatic_actions(
        self, decision: IterationDecision, context: WorkflowContext
    ) -> None:
        previous = self._last_applied_actions(context)
        patch: dict[str, Any] = {}
        applied: list[str] = []
        for action in decision.automatic_actions:
            action_name = str(action.get("action", ""))
            if action_name not in _FEEDBACK_ACTION_TARGETS and not action_name.startswith(
                "propose_"
            ):
                context.emit(
                    "feedback_action_ignored", f"未知反馈动作: {action_name}", status="warning"
                )
                continue
            if previous and previous[-1] == action_name:
                context.emit(
                    "feedback_action_ignored",
                    f"动作 {action_name} 连续重复，按规则忽略",
                    status="warning",
                )
                continue
            applied.append(action_name)
            parameters = action.get("parameters") or {}
            if (
                action_name == "adjust_registered_weights"
                and isinstance(parameters, dict)
                and parameters
            ):
                patch["weights"] = parameters
            if action_name == "tighten_detour_limit" and isinstance(parameters, dict):
                limit = parameters.get("detour_limit")
                if isinstance(limit, (int, float)) and not isinstance(limit, bool):
                    patch["detour_limit"] = float(limit)
        if patch:
            context.write_derived_config(patch, reason="反馈迭代自动调整")
        state = context.state
        state.applied_action_log.extend(f"iteration-{state.iteration}:{name}" for name in applied)
        if decision.proposed_code_changes:
            context.store.write_json_atomic(
                f"iterations/iteration-{state.iteration}/change_proposal.json",
                {"proposed_code_changes": decision.proposed_code_changes},
            )
        context.store.write_json_atomic(
            f"iterations/iteration-{state.iteration}/applied_actions.json",
            {"applied": applied, "iteration": state.iteration},
        )
        context.store.save_state(state)

    def _last_applied_actions(self, context: WorkflowContext) -> list[str]:
        data = context.store.read_json(
            f"iterations/iteration-{context.state.iteration}/applied_actions.json"
        )
        applied = data.get("applied") if isinstance(data, dict) else None
        return [str(name) for name in applied] if isinstance(applied, list) else []

    def _archive_iteration_outputs(self, context: WorkflowContext, stage_names: list[str]) -> None:
        store = context.store
        for name in stage_names:
            data = store.read_stage_output(name)
            if data is not None:
                store.write_json_atomic(
                    f"stages/{name}/output.iter{context.state.iteration}.json", data
                )

    # -- 汇总 ----------------------------------------------------------------
    def _summary(self, context: WorkflowContext) -> RunSummary:
        state = context.state
        published = (context.store.run_dir / "publish" / "published.flag").is_file()
        warnings: list[str] = []
        error: dict[str, Any] | None = None
        for name, status in state.stage_statuses.items():
            if status != "failed":
                continue
            output = context.store.read_stage_output(name) or {}
            error = {
                "stage": name,
                "error_type": output.get("error_type", "unknown"),
                "message": output.get("error_message", "见该阶段 audit.json"),
            }
            warnings.append(f"失败阶段 {name}: {error['message']}")
            break
        if context.conclusion_status is not None:
            state.final_support_status = context.conclusion_status  # type: ignore[assignment]
            context.store.save_state(state)
        return RunSummary(
            run_id=context.run_id,
            workflow=context.workflow.name,
            status=state.status,
            final_support_status=state.final_support_status,
            iterations=state.iteration,
            stage_statuses=dict(state.stage_statuses),
            started_at=state.started_at,
            finished_at=state.finished_at,
            run_dir=str(context.store.run_dir),
            published=published,
            warnings=warnings,
            error=error,
        )

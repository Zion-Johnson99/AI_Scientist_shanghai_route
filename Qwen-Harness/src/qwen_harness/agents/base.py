"""角色化 Agent 基类与阶段公共工具（设计文档 01 §12.1）。

每个阶段处理器遵循冻结签名 ``stage_handler(context: WorkflowContext) ->
StageResult``。公共流程：构造阶段输入 → 调模型（在线）或要求离线夹具
（离线由引擎注入，绝不伪造）→ Pydantic 校验 → 经 RunStore 落盘 →
返回 ``StageResult``。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel

from ..errors import ModelUnavailableError, SkillError
from ..llm.audit import audit_to_dict
from ..logging_utils import get_logger
from ..models import GateResult, ModelCallAudit, StageResult

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..skills import SkillDocument
    from ..workflow.engine import WorkflowContext

LOGGER = get_logger("agents.base")

OutputT = TypeVar("OutputT", bound=BaseModel)


class BaseAgent(Generic[OutputT]):
    """角色化 Agent：角色提示词、输出模型与所需技能相互隔离。"""

    name: str = "base-agent"
    prompt_name: str = ""
    output_model: type[OutputT] = BaseModel  # type: ignore[assignment]
    required_skills: tuple[str, ...] = ()

    def stage_contract(self) -> str:
        """输出模型 JSON Schema，注入系统提示词的阶段契约段。"""
        return json.dumps(self.output_model.model_json_schema(), ensure_ascii=False, indent=2)

    def load_skills(self, context: "WorkflowContext") -> list["SkillDocument"]:
        """按 ``required_skills`` 取技能；缺失降级为警告不阻塞。"""
        if not self.required_skills:
            return []
        try:
            discovered = context.skills.discover()
        except SkillError as exc:
            LOGGER.warning("技能发现失败（%s 继续执行）: %s", self.name, exc.message)
            return []
        missing = [name for name in self.required_skills if name not in discovered]
        if missing:
            LOGGER.warning("Agent %s 缺少技能: %s", self.name, ", ".join(missing))
        return [discovered[name] for name in self.required_skills if name in discovered]

    def run(
        self,
        context: "WorkflowContext",
        user_payload: dict[str, Any],
    ) -> tuple[OutputT, ModelCallAudit]:
        """在线调用模型并返回结构化输出；离线/客户端缺失时报错。"""
        stage = context.stage_spec.name if context.stage_spec is not None else self.name
        if context.options.offline or context.model_client is None:
            raise ModelUnavailableError(
                f"阶段 {stage} 需要模型调用，但当前为离线模式且缺少对应夹具",
                stage=stage,
                run_id=context.run_id,
                suggested_action=(
                    f"补充 examples/fixtures/model-responses/{stage}.json，"
                    "或去掉 --offline 并配置 API Key"
                ),
            )
        if context.prompts is None:
            raise ModelUnavailableError(
                "PromptBuilder 不可用",
                stage=stage,
                run_id=context.run_id,
                suggested_action="确认 Qwen-Harness/prompts 目录与 llm.prompts 模块完整",
            )
        skills = self.load_skills(context)
        system_prompt = context.prompts.build_system_prompt(
            self.prompt_name, skills, self.stage_contract()
        )
        prompt_version = context.prompts.template_version(self.prompt_name)
        skill_hashes = {document.name: document.sha256 for document in skills}
        model_instance, audit = context.model_client.generate_structured(
            stage_name=stage,
            system_prompt=system_prompt,
            user_payload=user_payload,
            output_model=self.output_model,
            prompt_version=prompt_version,
            skill_hashes=skill_hashes,
        )
        return model_instance, audit


def write_model_audit(context: "WorkflowContext", stage: str, audit: ModelCallAudit) -> str:
    """把模型调用审计写入运行目录（不含任何推理内容）。"""
    relative = f"stages/{stage}/model_call.json"
    context.store.write_json_atomic(relative, audit_to_dict(audit))
    context.audit_extras["model_audit"] = audit_to_dict(audit)
    return relative


def passed_result(
    context: "WorkflowContext",
    output_model: BaseModel,
    *,
    summary: str,
    gate_result: GateResult | None = None,
    artifacts: list[str] | None = None,
    warnings: list[str] | None = None,
    extra_output: dict[str, Any] | None = None,
) -> StageResult:
    """构造 passed 状态的结果；阶段输出即模型 JSON（引擎负责落盘）。"""
    stage = context.stage_spec.name if context.stage_spec is not None else ""
    output: dict[str, Any] = output_model.model_dump(mode="json")
    if extra_output:
        # 只允许补充元信息键，不覆盖模型字段
        for key, value in extra_output.items():
            if key not in output:
                output[key] = value
    context.emit(
        "stage_output_ready",
        f"{stage} 输出已通过契约校验",
        details={"model": type(output_model).__name__},
    )
    return StageResult(
        stage=stage,
        status="passed",
        summary=summary,
        output=output,
        gate_result=gate_result,
        artifacts=list(artifacts or []),
        warnings=list(warnings or []),
    )


def gate_failed_result(
    context: "WorkflowContext", gate_result: GateResult, message: str
) -> StageResult:
    """门禁未通过：阶段失败，违规项写入 GateResult。"""
    stage = context.stage_spec.name if context.stage_spec is not None else ""
    failed = [check.name for check in gate_result.checks if not check.passed]
    return StageResult(
        stage=stage,
        status="failed",
        summary=f"{message}: {', '.join(failed)}",
        output={"error_type": "gate_failed", "error_message": message},
        gate_result=gate_result,
        exit_code=1,
    )


def read_dependency(context: "WorkflowContext", stage: str) -> dict[str, Any]:
    """读取上游阶段输出；缺失时报可操作的输入契约错误。"""
    from ..errors import InputContractError

    data = context.read_stage_output(stage)
    if data is None:
        raise InputContractError(
            f"上游阶段 {stage} 尚无输出",
            stage=context.stage_spec.name if context.stage_spec else None,
            run_id=context.run_id,
            suggested_action=f"先执行 {stage} 阶段",
        )
    return data

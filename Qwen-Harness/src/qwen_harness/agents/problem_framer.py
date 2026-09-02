"""ProblemFramer：problem_framing 阶段（设计文档 01 §12.2）。

把 ResearchGoal 转写为可测量、有边界的 ProblemFrame。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import ProblemFrame, StageResult
from .base import BaseAgent, passed_result, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext


class ProblemFramerAgent(BaseAgent[ProblemFrame]):
    name = "problem-framer"
    prompt_name = "problem-framer"
    output_model = ProblemFrame
    required_skills = ("qwen-harness-orchestration", "scientific-evidence-hypothesis")


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    goal = context.goal
    derived = context.read_derived_config()
    return {
        "stage": "problem_framing",
        "iteration": context.iteration,
        "research_goal": goal.model_dump(mode="json"),
        "project_context": {
            "region": goal.region,
            "target_population": goal.target_population,
            "data_proxies": [
                "PM2.5 为网格/站点融合估计，不是逐地址观测",
                "花粉为日级背景/代理，不是实时浓度",
                "噪声为 0-100 风险代理，不是实测分贝",
            ],
            "candidate_scope": "仅当前候选路线集（约束最优，不宣称全路网最优）",
            "derived_config_keys": sorted(derived.keys()),
        },
    }


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = ProblemFramerAgent()
    frame, audit = agent.run(context, _build_payload(context))
    artifact = write_model_audit(context, "problem_framing", audit)
    return passed_result(
        context,
        frame,
        summary=f"问题框架就绪：{len(frame.measurable_objectives)} 个可测量目标",
        artifacts=[artifact],
    )

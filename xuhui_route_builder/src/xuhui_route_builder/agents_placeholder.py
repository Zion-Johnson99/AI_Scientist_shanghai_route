from __future__ import annotations

from pydantic import BaseModel, Field


class AgentResearchInput(BaseModel):
    user_question: str
    route_ids: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)


class AgentResearchPlan(BaseModel):
    problem_statement: str
    rationale: str
    technical_details: list[str]
    datasets: list[str]
    methods: list[str]
    experiments: list[str]
    references: list[str]


def build_placeholder_plan(request: AgentResearchInput) -> AgentResearchPlan:
    return AgentResearchPlan(
        problem_statement=f"围绕 {request.user_question} 生成可验证研究问题。",
        rationale="Qwen/百炼多 Agent 工作流后续接入，本阶段只固定输入输出结构。",
        technical_details=["路线库", "入口池", "接驳导航样例", "后续环境评分接口"],
        datasets=request.evidence_paths,
        methods=["人工 seed 路线生成", "高德路径规划", "GeoJSON 可视化"],
        experiments=["推荐路线与最短路线对比实验后续接入"],
        references=[],
    )

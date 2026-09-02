"""角色化科研 Agent（设计文档 01 §12）。

九个角色共享同一模型客户端，通过角色提示词、输入数据与输出模型隔离：

- ProblemFramer（problem_framing）
- EvidenceAgent（evidence_extraction）
- GapAgent（gap_analysis）
- HypothesisAgent（hypothesis_generation）
- CriticAgent（hypothesis_critique / hypothesis_selection）
- ExperimentAgent（experiment_design）
- ResultAgent（实验结果解释）
- FeedbackAgent（feedback_decision）
- ReportAgent（scientific_report）

每个阶段处理器遵循冻结签名 ``stage_handler(context) -> StageResult``。
"""

from .base import BaseAgent, gate_failed_result, passed_result, read_dependency, write_model_audit
from .critic_agent import CriticAgent
from .critic_agent import selection_stage_handler as hypothesis_selection_stage_handler
from .critic_agent import stage_handler as hypothesis_critique_stage_handler
from .evidence_agent import EvidenceAgent
from .experiment_agent import ExperimentAgent
from .feedback_agent import FeedbackAgent
from .gap_agent import GapAgent
from .hypothesis_agent import HypothesisAgent
from .problem_framer import ProblemFramerAgent
from .report_agent import ReportAgent
from .result_agent import ResultAgent

__all__ = [
    "BaseAgent",
    "CriticAgent",
    "EvidenceAgent",
    "ExperimentAgent",
    "FeedbackAgent",
    "GapAgent",
    "HypothesisAgent",
    "ProblemFramerAgent",
    "ReportAgent",
    "ResultAgent",
    "gate_failed_result",
    "hypothesis_critique_stage_handler",
    "hypothesis_selection_stage_handler",
    "passed_result",
    "read_dependency",
    "write_model_audit",
]

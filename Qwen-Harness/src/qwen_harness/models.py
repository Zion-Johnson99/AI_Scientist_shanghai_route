"""Pydantic v2 data models shared across the harness (design doc section 6).

All models are strict (``extra="forbid"``). Stage handlers, adapters, agents
and the CLI exchange data only through these models and their JSON form.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

HARNESS_SCHEMA_VERSION = "1.0"

SourceType = Literal["local_file", "pubmed", "crossref", "https_url", "repository_file"]
StageStatus = Literal["pending", "running", "passed", "needs_approval", "retryable", "failed", "skipped"]
SupportStatus = Literal["supported", "partially_supported", "unsupported", "inconclusive", "error"]
RunStatus = Literal["running", "passed", "failed", "needs_approval"]
ModuleKey = Literal["route", "environment", "evaluation", "web"]
ApprovalLevel = Literal["none", "critical", "always"]
ApprovalMode = Literal["auto", "critical", "all"]
RefreshTier = Literal["none", "weather", "hourly", "daily"]
ReasoningEffort = Literal["low", "medium", "high"]

AutomaticFeedbackAction = Literal[
    "expand_sources",
    "refresh_environment",
    "rerun_profiles",
    "rerun_variant",
    "adjust_registered_weights",
    "tighten_detour_limit",
    "relax_noncritical_filter",
]
ProposedFeedbackAction = Literal[
    "propose_route_data_change",
    "propose_environment_model_change",
    "propose_scoring_code_change",
    "propose_frontend_change",
]
FeedbackAction = Union[AutomaticFeedbackAction, ProposedFeedbackAction]

AUTOMATIC_FEEDBACK_ACTIONS = frozenset(
    {
        "expand_sources",
        "refresh_environment",
        "rerun_profiles",
        "rerun_variant",
        "adjust_registered_weights",
        "tighten_detour_limit",
        "relax_noncritical_filter",
    }
)
PROPOSED_FEEDBACK_ACTIONS = frozenset(
    {
        "propose_route_data_change",
        "propose_environment_model_change",
        "propose_scoring_code_change",
        "propose_frontend_change",
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Research input
# ---------------------------------------------------------------------------
class ResearchGoal(StrictModel):
    title: str
    question: str
    domain: str = "urban_environmental_health"
    region: str = "Shanghai Xuhui"
    target_population: str = "outdoor walkers, runners and cyclists"
    desired_outcome: str = ""
    constraints: list[str] = Field(default_factory=list)
    seed_sources: list[str] = Field(default_factory=list)


class RunOptions(StrictModel):
    workflow: str = "full-research"
    offline: bool = False
    allow_network: bool = False
    refresh_environment: RefreshTier = "none"
    approval_mode: ApprovalMode = "critical"
    max_iterations: int = Field(default=2, ge=1, le=16)
    publish_web: bool = False
    run_id: str | None = None
    json_output: bool = False

    @model_validator(mode="after")
    def _check_mode_combinations(self) -> "RunOptions":
        if self.offline and self.allow_network:
            raise ValueError("--offline 与 --allow-network 互斥")
        if self.offline and self.refresh_environment != "none":
            raise ValueError("--offline 模式下不能刷新环境数据")
        if self.refresh_environment != "none" and not self.allow_network:
            raise ValueError("--refresh-environment 非 none 时必须同时提供 --allow-network")
        return self


class ResumeOptions(StrictModel):
    publish_web: bool = False
    force_continue: bool = False


# ---------------------------------------------------------------------------
# Run bookkeeping
# ---------------------------------------------------------------------------
class RunEvent(StrictModel):
    ts: datetime
    run_id: str
    stage: str | None = None
    event_type: str
    status: str | None = None
    message: str = ""
    details: dict[str, object] = Field(default_factory=dict)
    elapsed_ms: float | None = None


class RunManifest(StrictModel):
    schema_version: str = HARNESS_SCHEMA_VERSION
    run_id: str
    created_at: datetime
    repo_root: str
    git_branch: str | None = None
    git_head: str | None = None
    worktree_clean: bool | None = None
    harness_version: str
    python_version: str
    platform: str
    model_name: str
    temperature: float
    seed: int
    stage_reasoning_effort: dict[str, str] = Field(default_factory=dict)
    workflow_name: str
    workflow_version: str
    skills_hashes: dict[str, str] = Field(default_factory=dict)
    config_hashes: dict[str, str] = Field(default_factory=dict)
    module_data_hashes: dict[str, str] = Field(default_factory=dict)
    network_enabled: bool
    module_write_enabled: bool = False
    publish_enabled: bool
    approval_mode: str
    offline: bool


class RunState(StrictModel):
    run_id: str
    status: RunStatus = "running"
    current_stage: str | None = None
    iteration: int = 1
    max_iterations: int = 2
    stage_statuses: dict[str, StageStatus] = Field(default_factory=dict)
    stage_input_hashes: dict[str, str] = Field(default_factory=dict)
    drift_records: list[dict[str, object]] = Field(default_factory=list)
    applied_action_log: list[str] = Field(default_factory=list)
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    final_support_status: SupportStatus | None = None
    notes: list[str] = Field(default_factory=list)


class RunContext(StrictModel):
    run_id: str
    run_dir: str
    goal: ResearchGoal
    options: RunOptions
    manifest: RunManifest
    state: RunState


class RunSummary(StrictModel):
    run_id: str
    workflow: str
    status: str
    final_support_status: SupportStatus | None = None
    iterations: int = 1
    stage_statuses: dict[str, StageStatus] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    run_dir: str
    published: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, object] | None = None


class HarnessSettings(StrictModel):
    """Environment-derived settings loaded from .env by config.py."""

    api_key: str = ""
    base_url: str = ""
    model: str = "qwen3.8-max"
    timeout_seconds: int = Field(default=180, ge=1)
    network_enabled: bool = False
    max_iterations: int = Field(default=2, ge=1, le=16)
    default_reasoning_effort: ReasoningEffort = "medium"
    runtime_root: str = "runtime"
    env_file_exists: bool = False

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def base_url_has_placeholder(self) -> bool:
        return (not self.base_url.strip()) or "<WorkspaceId>" in self.base_url


class ModelCallAudit(StrictModel):
    stage: str
    model: str
    created_at: datetime
    request_id: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_version: str | None = None
    reasoning_effort: str | None = None
    skill_hashes: dict[str, str] = Field(default_factory=dict)
    error_type: str | None = None


# ---------------------------------------------------------------------------
# Sources and evidence
# ---------------------------------------------------------------------------
class SourceRequest(StrictModel):
    request_id: str | None = None
    terms: list[str] = Field(default_factory=list)
    source_types: list[SourceType] = Field(
        default_factory=lambda: ["local_file", "repository_file", "pubmed", "crossref", "https_url"]
    )
    max_results: int = Field(default=10, ge=1, le=200)
    allowed_domains: list[str] = Field(default_factory=list)
    local_paths: list[str] = Field(default_factory=list)
    notes: str | None = None


class SourceRecord(StrictModel):
    source_id: str
    source_type: SourceType
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None
    local_path: str | None = None
    accessed_at: datetime
    sha256: str
    license_note: str
    verification_status: Literal["verified", "partial", "unverified", "rejected"]


class ExtractedDocument(StrictModel):
    source_id: str
    pages: list[str] = Field(default_factory=list)
    page_count: int = 0
    total_chars: int = 0
    sha256: str = ""
    requires_ocr: bool = False
    note: str | None = None


class EvidenceClaim(StrictModel):
    claim_id: str
    source_id: str
    claim: str
    evidence_location: str
    short_excerpt: str | None = None
    evidence_type: Literal["result", "method", "dataset", "limitation", "definition", "policy"]
    support_strength: Literal["high", "medium", "low"]
    caveats: list[str] = Field(default_factory=list)


class EvidenceCard(StrictModel):
    card_id: str
    research_question: str
    source_ids: list[str] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    notes: str | None = None


# ---------------------------------------------------------------------------
# Gaps and hypotheses
# ---------------------------------------------------------------------------
class KnowledgeGap(StrictModel):
    gap_id: str
    statement: str
    supported_by_claim_ids: list[str] = Field(default_factory=list)
    affected_variables: list[str] = Field(default_factory=list)
    why_unresolved: str
    available_data: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    testability: Literal["high", "medium", "low"]
    product_relevance: Literal["high", "medium", "low"]


class KnowledgeGapSet(StrictModel):
    gaps: list[KnowledgeGap] = Field(default_factory=list)
    summary: str | None = None


class HypothesisCandidate(StrictModel):
    hypothesis_id: str
    statement: str
    mechanism: str
    independent_variables: list[str] = Field(default_factory=list)
    dependent_variables: list[str] = Field(default_factory=list)
    moderators: list[str] = Field(default_factory=list)
    expected_direction: str
    falsification_criteria: list[str] = Field(default_factory=list)
    required_data: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    novelty_argument: str
    feasibility_score: float
    scientific_value_score: float
    risks: list[str] = Field(default_factory=list)


class HypothesisSet(StrictModel):
    hypotheses: list[HypothesisCandidate] = Field(default_factory=list)
    recommended_hypothesis_id: str
    selection_rationale: str


class HypothesisAssessment(StrictModel):
    hypothesis_id: str
    verdict: Literal["accept", "revise", "reject"]
    novelty_notes: str = ""
    feasibility_notes: str = ""
    counterexamples: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class HypothesisReview(StrictModel):
    assessments: list[HypothesisAssessment] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    selected_hypothesis_id: str
    selection_rationale: str


# ---------------------------------------------------------------------------
# Experiment plan
# ---------------------------------------------------------------------------
class BaselineSpec(StrictModel):
    baseline_id: str
    name: str
    selection_rule: str
    required_fields: list[str] = Field(default_factory=list)


class MetricSpec(StrictModel):
    metric_id: str
    name: str
    direction: Literal["higher", "lower", "target"]
    formula: str
    primary: bool
    data_source: str


class ModuleOperation(StrictModel):
    operation_id: str
    module: ModuleKey
    parameters: dict[str, object] = Field(default_factory=dict)
    reason: str | None = None


class ExperimentPlan(StrictModel):
    hypothesis_id: str
    profiles: list[dict[str, object]] = Field(default_factory=list)
    baselines: list[BaselineSpec] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)
    detour_limit: float
    target_distance_tolerance: float
    module_operations: list[ModuleOperation] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Module execution
# ---------------------------------------------------------------------------
class CommandAudit(StrictModel):
    command_id: str
    argv: list[str]
    cwd: str
    started_at: datetime
    finished_at: datetime
    exit_code: int
    stdout_path: str
    stderr_path: str
    timeout: bool


class ModuleResult(StrictModel):
    module: ModuleKey
    status: Literal["ok", "partial", "skipped", "error"]
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    data_hashes: dict[str, str] = Field(default_factory=dict)
    commands: list[CommandAudit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Iteration, interpretation and final plan
# ---------------------------------------------------------------------------
class IterationDecision(StrictModel):
    status: Literal["continue", "stop_supported", "stop_partial", "stop_unsupported", "stop_inconclusive"]
    reason: str
    automatic_actions: list[dict[str, object]] = Field(default_factory=list)
    proposed_code_changes: list[dict[str, object]] = Field(default_factory=list)
    next_iteration_goal: str | None = None


class ProblemFrame(StrictModel):
    problem_statement: str
    measurable_objectives: list[str] = Field(default_factory=list)
    scope_boundaries: list[str] = Field(default_factory=list)
    key_variables: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ResultInterpretation(StrictModel):
    status: SupportStatus
    interpretation: str
    metric_highlights: list[dict[str, object]] = Field(default_factory=list)
    negative_results: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class PlanDatasets(StrictModel):
    source: list[str] = Field(default_factory=list)
    target: list[str] = Field(default_factory=list)


class PlanExperiments(StrictModel):
    baselines: list[BaselineSpec] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)


class PlanReference(StrictModel):
    source_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None


class ScientificPlan(StrictModel):
    schema_version: str = HARNESS_SCHEMA_VERSION
    run_id: str
    git_head: str = ""
    problem_statement: str
    rationale: str
    technical_details: list[str] = Field(default_factory=list)
    datasets: PlanDatasets
    paper_title: str
    paper_abstract: str
    methods: list[str] = Field(default_factory=list)
    experiments: PlanExperiments
    results: dict[str, object] = Field(default_factory=dict)
    references: list[PlanReference] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    reproducibility: dict[str, object] = Field(default_factory=dict)
    data_snapshot_hashes: dict[str, str] = Field(default_factory=dict)
    generated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Web payload
# ---------------------------------------------------------------------------
class SelectedRoute(StrictModel):
    route_id: str
    route_name: str
    reason: str


class WebPayload(StrictModel):
    schema_version: str = HARNESS_SCHEMA_VERSION
    run_id: str
    generated_at: datetime
    status: SupportStatus
    research_question: str
    hypothesis: str
    selected_route: SelectedRoute | None = None
    key_metrics: list[dict[str, object]] = Field(default_factory=list)
    baseline_comparison: list[dict[str, object]] = Field(default_factory=list)
    iterations: list[dict[str, object]] = Field(default_factory=list)
    references: list[dict[str, object]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workflow configuration and stage contracts
# ---------------------------------------------------------------------------
class StageSpec(StrictModel):
    name: str
    handler: str
    required_skills: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    approval: ApprovalLevel = "none"
    retry_limit: int = Field(default=0, ge=0, le=10)
    enabled: bool = True


class WorkflowConfig(StrictModel):
    schema_version: str = HARNESS_SCHEMA_VERSION
    name: str
    version: str = "1.0"
    description: str = ""
    offline_fixture: bool = False
    stages: list[StageSpec]


class GateCheck(StrictModel):
    name: str
    passed: bool
    detail: str | None = None


class GateResult(StrictModel):
    gate: str
    passed: bool
    checks: list[GateCheck] = Field(default_factory=list)
    summary: str | None = None


class StageResult(StrictModel):
    stage: str
    status: StageStatus
    summary: str | None = None
    output: dict[str, object] = Field(default_factory=dict)
    gate_result: GateResult | None = None
    artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retryable: bool = False
    exit_code: int | None = None


class ApprovalGate(StrictModel):
    stage: str
    level: ApprovalLevel
    reason: str
    details: dict[str, object] = Field(default_factory=dict)


class ApprovalDecision(StrictModel):
    approved: bool
    approver: str
    reason: str
    decided_at: datetime

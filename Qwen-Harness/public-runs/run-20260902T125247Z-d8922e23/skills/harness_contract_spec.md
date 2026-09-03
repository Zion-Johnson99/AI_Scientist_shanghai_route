# Qwen-Harness Contract Spec (Round 2 / 第二轮)

Implementation-ready extraction of every harness contract that round-2 generated
artifacts must satisfy. All identifiers, paths, enum values, thresholds and
command strings are quoted **verbatim** from the harness source. Items that are
not literally present in the source are marked **[inferred]**.

Sources read (read-only): `Qwen-Harness/README.md`, `Qwen-Harness/pyproject.toml`,
`Qwen-Harness/src/qwen_harness/**`, `Qwen-Harness/config/**`,
`Qwen-Harness/schemas/**`, `Qwen-Harness/prompts/**` (listing),
`Qwen-Harness/tests/**`, `Qwen-Harness/scripts/generated_browser_gate.py`,
`.github/workflows/qwen-harness-ci.yml`,
`docs/qwen-harness-build/**` (listing).
Nothing under `xuhui_route_builder/`, `weather_api_data/`,
`evaluation_model_qwen/`, `runtime/runs/*/workspace/source/**` or
`runtime/runs/*/publish/**` was read.

Repo root: `<repo_root>`
Harness root: `<repo>\Qwen-Harness`
This run: `<harness>\runtime\runs\run-20260902T125247Z-d8922e23`

---

## 1. Run directory layout

`RUN_SUBDIRS` (created eagerly by `RunStore.create_run`) —
`src/qwen_harness/run_store.py`:

```python
RUN_SUBDIRS = ("inputs", "sources", "skills", "stages", "modules", "experiments", "reports", "publish")
```

Additional directories are created lazily by writers: `checks/`, `commands/`,
`iterations/`, `workspace/`, `workspace/source/`, `checks/browser/`.

```text
runtime/runs/<run-id>/
├── run_manifest.json            # RunManifest
├── state.json                   # RunState
├── lock.json                    # {pid, hostname, run_id, acquired_at}
├── events.jsonl                 # append-only RunEvent stream
├── derived_config.json          # feedback-iteration derived config patch (merged dict)
├── inputs/
│   ├── research_goal.json       # ResearchGoal
│   └── run_options.json         # RunOptions
├── sources/
│   ├── source_registry.jsonl    # one SourceRecord per line
│   ├── evidence_cards.jsonl     # one EvidenceCard per line
│   └── extracted_texts.json     # {source_id: ExtractedDocument}
├── skills/<skill-name>/SKILL.md # snapshot of .qoder/skills (+ referenced files)
├── stages/<stage>/
│   ├── input.json               # _STAGE_KINDS["input"]
│   ├── output.json              # _STAGE_KINDS["output"] (only when status in {passed, failed})
│   ├── audit.json               # _STAGE_KINDS["audit"]
│   ├── model_call.json          # ModelCallAudit (agent stages)
│   ├── model_audits.json        # project_generation only
│   ├── approval.json            # when an approval gate fires
│   ├── gate_detail.json         # citation_validation only
│   └── output.iter<N>.json      # archived before a feedback jump-back
├── workspace/
│   ├── architecture.json        # ArchitecturePlan
│   ├── generation_result.json   # GenerationResult
│   └── source/                  # THE generated tree (all adapters read only here)
│       ├── Qwen-Harness/
│       ├── evaluation_model_qwen/
│       ├── weather_api_data/
│       └── xuhui_route_builder/
├── modules/
│   ├── route/preflight.json, snapshot.json, read_snapshot.json
│   ├── environment/preflight.json, snapshot.json, read_snapshot.json
│   ├── evaluation/preflight.json, score_candidates__<case>.json,
│   │               <case>_input.json
│   └── web/preflight.json, export_payload.json
├── experiments/
│   ├── experiment_results.json
│   ├── metrics_summary.json
│   └── score_candidates/<case_id>__<variant_id>.json
├── reports/
│   ├── scientific_plan.json     # ScientificPlan (REQUIRED by final_validation)
│   ├── scientific_plan.md
│   ├── experiment_report.md
│   ├── reproducibility.md
│   ├── full_run_report.md
│   └── metrics_summary.json     # byte-identical content to experiments/metrics_summary.json
├── checks/
│   ├── generation_contract.json # FunctionalContractReport
│   ├── generated_quality.json   # GeneratedQualityReport
│   ├── runtime_repairs.json     # only if a runtime repair happened
│   └── browser/
│       ├── browser_acceptance.json
│       ├── local-desktop.png / local-mobile.png
│       ├── local-<name>-failure.png (on failure)
│       └── online-desktop.png / online-mobile.png
├── commands/<command_id>.stdout.log, <command_id>.stderr.log
├── iterations/iteration-<N>/
│   ├── decision.json            # IterationDecision
│   ├── applied_actions.json
│   └── change_proposal.json
└── publish/
    ├── research_harness_latest.json   # staged WebPayload (consumed then moved)
    ├── published.flag
    ├── source/<4 modules>/**
    ├── local-product/web/**, local-product/data/web/**
    ├── reports/完整运行报告.md, 科学计划.md, 实验报告.md
    ├── checks/**
    ├── launch-local.ps1
    └── source_manifest.json
```

Run id: `generate_run_id()` → `run-%Y%m%dT%H%M%SZ-<uuid4().hex[:8]>`; must match
`RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")`.

Every write goes through `write_json_atomic` / `write_bytes_atomic`:
tmp → flush → `os.fsync` → `os.replace`; JSON is serialized with
`indent=2, ensure_ascii=False` plus a trailing `"\n"`. `_resolve()` rejects any
relative path that escapes the run dir (`PathBoundaryError`).

`load_run` requires all four of: `inputs/research_goal.json`,
`inputs/run_options.json`, `run_manifest.json`, `state.json`.

---

## 2. `run_manifest.json` (model `RunManifest`)

`extra="forbid"`. Field order as declared in `src/qwen_harness/models.py`:

| field | type | notes |
| --- | --- | --- |
| `schema_version` | `str` | default `HARNESS_SCHEMA_VERSION = "1.0"` |
| `run_id` | `str` | required |
| `created_at` | `datetime` | required |
| `repo_root` | `str` | required |
| `git_branch` | `str \| None` | |
| `git_head` | `str \| None` | |
| `worktree_clean` | `bool \| None` | |
| `harness_version` | `str` | required |
| `python_version` | `str` | required |
| `platform` | `str` | required |
| `model_name` | `str` | required |
| `temperature` | `float` | required |
| `seed` | `int` | required |
| `stage_reasoning_effort` | `dict[str, str]` | default `{}` |
| `workflow_name` | `str` | required |
| `workflow_version` | `str` | required |
| `skills_hashes` | `dict[str, str]` | default `{}` |
| `config_hashes` | `dict[str, str]` | default `{}` |
| `module_data_hashes` | `dict[str, str]` | default `{}` |
| `network_enabled` | `bool` | required; `options.allow_network and not options.offline` |
| `module_write_enabled` | `bool` | default `False` — **must stay `False`** |
| `publish_enabled` | `bool` | required; `options.publish_web` |
| `approval_mode` | `str` | required |
| `offline` | `bool` | required |

---

## 3. `state.json` (`RunState`) and `events.jsonl` (`RunEvent`)

`RunState`:

| field | type | default |
| --- | --- | --- |
| `run_id` | `str` | required |
| `status` | `RunStatus` | `"running"` |
| `current_stage` | `str \| None` | `None` |
| `iteration` | `int` | `1` |
| `max_iterations` | `int` | `2` |
| `stage_statuses` | `dict[str, StageStatus]` | `{}` |
| `stage_input_hashes` | `dict[str, str]` | `{}` |
| `drift_records` | `list[dict[str, object]]` | `[]` |
| `applied_action_log` | `list[str]` | `[]` |
| `started_at` | `datetime` | required |
| `updated_at` | `datetime` | required |
| `finished_at` | `datetime \| None` | `None` |
| `final_support_status` | `SupportStatus \| None` | `None` |
| `notes` | `list[str]` | `[]` |

`RunEvent` (one JSON object per line of `events.jsonl`):

| field | type | default |
| --- | --- | --- |
| `ts` | `datetime` | required |
| `run_id` | `str` | required |
| `stage` | `str \| None` | `None` |
| `event_type` | `str` | required |
| `status` | `str \| None` | `None` |
| `message` | `str` | `""` |
| `details` | `dict[str, object]` | `{}` |
| `elapsed_ms` | `float \| None` | `None` |

Enums (verbatim):

```python
StageStatus  = Literal["pending","running","passed","needs_approval","retryable","failed","skipped"]
SupportStatus= Literal["supported","partially_supported","unsupported","inconclusive","error"]
RunStatus    = Literal["running","passed","failed","needs_approval"]
ModuleKey    = Literal["route","environment","evaluation","web"]
ApprovalLevel= Literal["none","critical","always"]
ApprovalMode = Literal["auto","critical","all"]
RefreshTier  = Literal["none","weather","hourly","daily"]
ReasoningEffort = Literal["low","medium","high"]
```

`StageResult` (returned by every handler, `stage_handler(context) -> StageResult`):
`stage`, `status: StageStatus`, `summary: str|None`, `output: dict`,
`gate_result: GateResult|None`, `artifacts: list[str]`, `warnings: list[str]`,
`retryable: bool = False`, `exit_code: int|None`.
`GateResult` = `{gate: str, passed: bool, checks: list[GateCheck], summary: str|None}`;
`GateCheck` = `{name: str, passed: bool, detail: str|None}`.

Engine retry policy: `MAX_RETRIES = 2`, `RETRY_BACKOFF_SECONDS = (1.0, 2.0)`.

---

## 4. Ordered stage list + per-stage artifacts

`config/workflows/full-research.json` — **19 stages**, in this exact order
(`schema_version="1.0"`, `name="full-research"`, `version="1.0"`,
`offline_fixture=false`):

| # | stage | handler (`"module:function"`) | approval | dependencies |
| --- | --- | --- | --- | --- |
| 1 | `initialize` | `qwen_harness.workflow.stages:initialize_stage` | none | — |
| 2 | `problem_framing` | `qwen_harness.agents.problem_framer:stage_handler` | none | `initialize` |
| 3 | `source_collection` | `qwen_harness.sources.base:source_collection_stage` | none | `problem_framing` |
| 4 | `evidence_extraction` | `qwen_harness.agents.evidence_agent:stage_handler` | none | `source_collection` |
| 5 | `citation_validation` | `qwen_harness.sources.citation_gate:stage_handler` | none | `evidence_extraction` |
| 6 | `gap_analysis` | `qwen_harness.agents.gap_agent:stage_handler` | none | `citation_validation` |
| 7 | `hypothesis_generation` | `qwen_harness.agents.hypothesis_agent:stage_handler` | none | `gap_analysis` |
| 8 | `hypothesis_critique` | `qwen_harness.agents.critic_agent:stage_handler` | none | `hypothesis_generation` |
| 9 | `hypothesis_selection` | `qwen_harness.agents.critic_agent:selection_stage_handler` | none | `hypothesis_critique` |
| 10 | `experiment_design` | `qwen_harness.agents.experiment_agent:stage_handler` | none | `hypothesis_selection` |
| 11 | `project_generation` | `qwen_harness.generation.stage_handlers:stage_handler` | none | `experiment_design` |
| 12 | `module_preflight` | `qwen_harness.workflow.stages:module_preflight_stage` | none | `project_generation` |
| 13 | `module_execution` | `qwen_harness.workflow.stages:module_execution_stage` | **critical** | `module_preflight` |
| 14 | `experiment_analysis` | `qwen_harness.experiments.runner:stage_handler` | none | `module_execution` |
| 15 | `feedback_decision` | `qwen_harness.agents.feedback_agent:stage_handler` | none | `experiment_analysis` |
| 16 | `scientific_report` | `qwen_harness.agents.report_agent:stage_handler` | none | `feedback_decision` |
| 17 | `web_payload` | `qwen_harness.reporting.web_payload:stage_handler` | none | `scientific_report` |
| 18 | `final_validation` | `qwen_harness.workflow.stages:final_validation_stage` | none | `web_payload` |
| 19 | `publish_web` | `qwen_harness.workflow.stages:publish_web_stage` | **always** | `final_validation` |

`research-only` = the same list **minus** `project_generation`,
`module_preflight`, `module_execution`, `experiment_analysis`, `publish_web`
(14 stages; `feedback_decision` then depends on `experiment_design`).
`reproduce-existing` = the same 19 stages with `offline_fixture: true`.

Per-stage `output.json` model + written artifacts:

| stage | output model / shape | extra artifacts written |
| --- | --- | --- |
| `initialize` | `{skills_snapshotted: [str], skills_missing: [str], derived_config_keys: [str]}` | `skills/<name>/SKILL.md` (+ referenced files), `derived_config.json` (`{supported_thresholds, weights:{}}` then `{experiment_variants}`) |
| `problem_framing` | `ProblemFrame` | `stages/problem_framing/model_call.json` |
| `source_collection` | `{source_count:int, source_ids:[str], verified_count:int, network_enabled:bool, network_skipped:int}` (online) or `{..., fixture:true}` (offline) | `sources/source_registry.jsonl`, `sources/extracted_texts.json` |
| `evidence_extraction` | `EvidenceCard` | `sources/evidence_cards.jsonl`, `model_call.json` |
| `citation_validation` | `{claims_checked:int, sources_checked:int, cards:int}`; on failure `{error_type:"gate_failed", error_message:..., claims_checked:int}` | `stages/citation_validation/gate_detail.json` |
| `gap_analysis` | `KnowledgeGapSet` | `model_call.json` |
| `hypothesis_generation` | `HypothesisSet` | `model_call.json` |
| `hypothesis_critique` | `HypothesisReview` (mode `critique`) | `model_call.json` |
| `hypothesis_selection` | `HypothesisReview` + `gate_result` from `HypothesisGate` | `model_call.json` |
| `experiment_design` | `ExperimentPlan` + `gate_result` (`gate="experiment_preregistration"`) | `model_call.json` |
| `project_generation` | `{provenance, score, threshold, passed, repair_rounds, remaining_issues, architecture, generation_result, checks, model_audits}` | `workspace/architecture.json`, `workspace/generation_result.json`, `workspace/source/**`, `checks/generation_contract.json`, `stages/project_generation/model_audits.json` |
| `module_preflight` | `{preflight_statuses: {route, environment, evaluation, web}}` | `modules/<m>/preflight.json` (ModuleResult) |
| `module_execution` | `{executed_operations: ["<module>:<operation_id>", ...]}` | `modules/<m>/<operation_id with "."→"_">[__<safe_label>].json`, `modules/route/snapshot.json`, `modules/environment/snapshot.json`, `modules/evaluation/<label>_input.json`, `experiments/score_candidates/<case>__<variant>.json`, `commands/*.log`, `checks/runtime_repairs.json` (only on repair) |
| `experiment_analysis` | `ResultInterpretation` | `experiments/experiment_results.json`, `experiments/metrics_summary.json`, `reports/metrics_summary.json` |
| `feedback_decision` | `IterationDecision` | `iterations/iteration-<N>/decision.json`, `applied_actions.json`, `change_proposal.json`, `derived_config.json` patch, archived `stages/<stage>/output.iter<N>.json` |
| `scientific_report` | `ScientificPlan` (with `run_id`, `generated_at` overwritten) | `reports/scientific_plan.json`, `reports/full_run_report.md`, `model_call.json` |
| `web_payload` | `WebPayload` | `publish/research_harness_latest.json`, `reports/scientific_plan.md`, `reports/experiment_report.md`, `reports/reproducibility.md` |
| `final_validation` | `{support_status, route_ids_checked:int, generation_score, result_gate, generated_quality}` | `checks/generated_quality.json`, `checks/browser/**`, `commands/*.log` |
| `publish_web` | `{published_to: <abs path>, local_url: "http://127.0.0.1:8130/web/"}` | whole `publish/**` tree, `publish/published.flag` = `{target:"publish/local-product", run_id, local_url}`; `artifacts=["publish/local-product/web/index.html","publish/source_manifest.json"]` |

`publish_web` hard-requires `state.stage_statuses["final_validation"] == "passed"`,
else it returns `status="failed"`, `exit_code=1`,
`output={"error_type":"gate_failed","error_message":"最终门禁未通过，禁止发布"}`.

Feedback jump-back targets (`_FEEDBACK_ACTION_TARGETS`) and `_DECISION_TO_CONCLUSION`
map `stop_supported→supported`, `stop_partial→partially_supported`,
`stop_unsupported→unsupported`, `stop_inconclusive→inconclusive`.

---

## 5. Schemas (`Qwen-Harness/schemas/*.schema.json`, all `additionalProperties: false`)

Twelve schema files: `research-goal`, `evidence-card`, `knowledge-gap`,
`hypothesis-set`, `experiment-plan`, `scientific-plan`, `module-result`,
`generation-architecture`, `generation-file`, `generation-repair`,
`iteration-decision`, `web-payload`. Required arrays and enums below are the
schema `required` lists cross-checked against the Pydantic models.

### 5.1 research-goal (`ResearchGoal`)
required: `title`, `question`.
`title: str`, `question: str`, `domain: str = "urban_environmental_health"`,
`region: str = "Shanghai Xuhui"`,
`target_population: str = "outdoor walkers, runners and cyclists"`,
`desired_outcome: str = ""`, `constraints: list[str] = []`,
`seed_sources: list[str] = []`.

`RunOptions`: `workflow="full-research"`, `offline=false`, `allow_network=false`,
`refresh_environment="none"`, `approval_mode="critical"`,
`max_iterations=2 (ge=1, le=16)`, `publish_web=false`, `run_id=None`,
`json_output=false`. Validator rejects `offline && allow_network`,
`offline && refresh_environment != "none"`,
`refresh_environment != "none" && !allow_network`.

### 5.2 evidence-card (`EvidenceCard` / `EvidenceClaim`)
`EvidenceCard` required: `card_id`, `research_question`.
`card_id: str`, `research_question: str`, `source_ids: list[str] = []`,
`claims: list[EvidenceClaim] = []`, `notes: str|None`.
`EvidenceClaim` required: `claim_id`, `source_id`, `claim`, `evidence_location`,
`evidence_type`, `support_strength`.
`evidence_type: Literal["result","method","dataset","limitation","definition","policy"]`,
`support_strength: Literal["high","medium","low"]`,
`short_excerpt: str|None`, `caveats: list[str] = []`.

`SourceRecord`: `source_id`, `source_type: SourceType`, `title`,
`authors: list[str]`, `year: int|None`, `doi: str|None`, `pmid: str|None`,
`url: str|None`, `local_path: str|None`, `accessed_at: datetime`, `sha256: str`,
`license_note: str`,
`verification_status: Literal["verified","partial","unverified","rejected"]`.
`SourceType = Literal["local_file","pubmed","crossref","https_url","repository_file"]`.

`ExtractedDocument`: `source_id`, `pages: list[str]`, `page_count: int`,
`total_chars: int`, `sha256: str`, `requires_ocr: bool`, `note: str|None`.

### 5.3 knowledge-gap (`KnowledgeGapSet` / `KnowledgeGap`)
`KnowledgeGapSet`: no top-level `required`; `gaps: list[KnowledgeGap] = []`,
`summary: str|None`.
`KnowledgeGap` required: `gap_id`, `statement`, `why_unresolved`, `testability`,
`product_relevance`.
`supported_by_claim_ids: list[str]`, `affected_variables: list[str]`,
`available_data: list[str]`, `missing_data: list[str]`,
`testability: Literal["high","medium","low"]`,
`product_relevance: Literal["high","medium","low"]`.

### 5.4 hypothesis-set (`HypothesisSet` / `HypothesisCandidate`)
`HypothesisSet` required: `recommended_hypothesis_id`, `selection_rationale`.
`hypotheses: list[HypothesisCandidate] = []`.
`HypothesisCandidate` required: `hypothesis_id`, `statement`, `mechanism`,
`expected_direction`, `novelty_argument`, `feasibility_score`,
`scientific_value_score`.
Optional: `independent_variables`, `dependent_variables`, `moderators`,
`falsification_criteria`, `required_data`, `supporting_claim_ids`, `risks`
(all `list[str] = []`); `feasibility_score: float`,
`scientific_value_score: float`.

`HypothesisReview` required: `selected_hypothesis_id`, `selection_rationale`;
`assessments: list[HypothesisAssessment]`, `conflicts: list[str]`,
`missing_evidence: list[str]`.
`HypothesisAssessment`: `hypothesis_id`,
`verdict: Literal["accept","revise","reject"]`, `novelty_notes`,
`feasibility_notes`, `counterexamples`, `missing_evidence`.

### 5.5 experiment-plan (`ExperimentPlan`)
required: `hypothesis_id`, `detour_limit`, `target_distance_tolerance`.
`profiles: list[dict] = []`, `baselines: list[BaselineSpec] = []`,
`variants: list[str] = []`, `metrics: list[MetricSpec] = []`,
`detour_limit: float`, `target_distance_tolerance: float`,
`module_operations: list[ModuleOperation] = []`,
`acceptance_criteria: list[str] = []`, `stop_conditions: list[str] = []`.
`BaselineSpec`: `baseline_id`, `name`, `selection_rule`, `required_fields`.
`MetricSpec` required: `metric_id`, `name`, `direction`, `formula`, `primary`,
`data_source`; `direction: Literal["higher","lower","target"]`, `primary: bool`.
`ModuleOperation`: `operation_id: str`, `module: ModuleKey`,
`parameters: dict`, `reason: str|None`.

Allowed `operation_id` values (`ALLOWED_OPERATION_IDS`):
`route.read_snapshot`, `environment.read_snapshot`,
`evaluation.score_candidates`, `web.export_payload`.
Synthetic (CLI-authorized only): `environment.refresh`.
Disabled in v1 (`DISABLED_OPERATIONS_V1`): `route_export_candidates`,
`route_generate`.

### 5.6 scientific-plan (`ScientificPlan`)
required: `run_id`, `problem_statement`, `rationale`, `datasets`, `paper_title`,
`paper_abstract`, `experiments`.
Also: `schema_version="1.0"`, `git_head: str = ""`,
`technical_details: list[str]`, `methods: list[str]`,
`results: dict[str, object]`, `references: list[PlanReference]`,
`evidence_map: dict[str, list[str]]`, `limitations: list[str]`,
`reproducibility: dict[str, object]`,
`data_snapshot_hashes: dict[str, str]`, `generated_at: datetime|None`.
`PlanDatasets`: `source: list[str]`, `target: list[str]`.
`PlanExperiments`: `baselines: list[BaselineSpec]`, `metrics: list[MetricSpec]`.
`PlanReference` required: `source_id`, `title`; optional `authors`, `year`,
`doi`, `pmid`, `url`.

### 5.7 module-result (`ModuleResult` / `CommandAudit`)
`ModuleResult` required: `module`, `status`.
`module: ModuleKey`, `status: Literal["ok","partial","skipped","error"]`,
`input_artifacts: list[str]`, `output_artifacts: list[str]`,
`data_hashes: dict[str,str]`, `commands: list[CommandAudit]`,
`warnings: list[str]`, `errors: list[str]`.
`CommandAudit` — **all nine fields required**: `command_id`, `argv: list[str]`,
`cwd: str`, `started_at: datetime`, `finished_at: datetime`, `exit_code: int`,
`stdout_path: str`, `stderr_path: str`, `timeout: bool`.

### 5.8 generation-architecture (`ArchitecturePlan`)
required: `summary`, `technology_choices`, `integration_contracts`, `files`.
Schema enforces `contains` patterns per project root and a `sourcePath` regex.
Model constraints (`generation/models.py`): `summary` ≥ 1 item,
`technology_choices` ≥ 1, `integration_contracts` ≥ 1, `files` 4–64 entries
covering **all four** roots, paths unique. `normalize_source_path`: POSIX
separators, ≥ 2 parts, no `..`/`.`, top-level dir ∈
`REQUIRED_PROJECT_ROOTS = ("Qwen-Harness","evaluation_model_qwen","weather_api_data","xuhui_route_builder")`.

### 5.9 generation-file (`GeneratedFile`)
required: `path`, `content`. `path: str`, `content: str`.

### 5.10 generation-repair (`RepairBatch`)
required: `summary`, `files`. `summary: str`, `files: list[GeneratedFile]` (≥ 1).
`ValidationIssue`: `check`, `summary`, `details`,
`severity: Literal["error","warning"]`, `files: list[str]`.

### 5.11 iteration-decision (`IterationDecision`)
required: `status`, `reason`.
`status: Literal["continue","stop_supported","stop_partial","stop_unsupported","stop_inconclusive"]`,
`reason: str`, `automatic_actions: list[dict] = []`,
`proposed_code_changes: list[dict] = []`, `next_iteration_goal: str|None`.
`AUTOMATIC_FEEDBACK_ACTIONS` = `expand_sources`, `refresh_environment`,
`rerun_profiles`, `rerun_variant`, `adjust_registered_weights`,
`tighten_detour_limit`, `relax_noncritical_filter`.
`PROPOSED_FEEDBACK_ACTIONS` = `propose_route_data_change`,
`propose_environment_model_change`, `propose_scoring_code_change`,
`propose_frontend_change`.
`status == "continue"` with empty `automatic_actions` → `InputContractError`.

### 5.12 web-payload (`WebPayload`)
required: `run_id`, `generated_at`, `status`, `research_question`, `hypothesis`.
`schema_version="1.0"`, `status: SupportStatus`,
`selected_route: SelectedRoute|None`, `key_metrics: list[dict]`,
`baseline_comparison: list[dict]`, `iterations: list[dict]`,
`references: list[dict]`, `limitations: list[str]`, `artifacts: list[str]`.
`SelectedRoute` required: `route_id`, `route_name`, `reason`.

### 5.13 Other models used by handlers
`ProblemFrame`: `problem_statement` (required), `measurable_objectives`,
`scope_boundaries`, `key_variables`, `assumptions`, `risks` (all `list[str]`).
`ResultInterpretation`: `status: SupportStatus`, `interpretation: str`,
`metric_highlights: list[dict]`, `negative_results: list[str]`,
`data_quality_notes: list[str]`,
`confidence: Literal["high","medium","low"] = "medium"`.
`ModelCallAudit`: `stage`, `model`, `created_at` required; `request_id`,
`latency_ms`, `input_tokens`, `output_tokens`, `prompt_version`,
`reasoning_effort`, `skill_hashes`, `error_type` optional — **never contains
reasoning content**.
`GenerationResult`: `source_root`, `architecture`, `written_files`,
`repair_rounds`, `remaining_issues`, `model_audits`.

---

## 6. Quality gates and `checks/generated_quality.json`

### 6.1 `config/quality_gates.json` (verbatim values)

```json
{
  "evidence":   { "min_verified_sources": 5, "reference_verification_rate_min": 1.0,
                  "require_evidence_location": true, "excerpt_max_chars": 400 },
  "hypothesis": { "min_candidates": 3, "require_falsification_criteria": true,
                  "require_variables": true },
  "experiment": { "require_baselines": true, "require_primary_metric": true,
                  "detour_limit_max": 0.3, "require_snapshot_hashes": true },
  "result":     { "require_module_provenance": true,
                  "composite_utility_as_sole_metric": false,
                  "require_negative_result_reporting": true },
  "supported":  { "detour_pass_rate_min": 0.9, "environment_win_rate_min": 0.6,
                  "preference_win_rate_min": 0.6,
                  "reference_verification_rate_min": 1.0,
                  "fatal_data_errors_max": 0, ...result keys... },
  "publish":    { "require_schema_version": "1.0", "forbid_absolute_paths": true,
                  "require_https_references": true,
                  "forbidden_tokens": ["DASHSCOPE_API_KEY","Authorization:","sk-"] }
}
```

`load_quality_gates` requires sections `evidence`, `hypothesis`, `experiment`,
`result`, `supported`, `publish` and the five `supported` keys.

### 6.2 Gate checks (`src/qwen_harness/workflow/gates.py`)

- **EvidenceGate**: `verified_source_count` (≥ 5), `reference_verification_rate`
  (≥ 1.0), `no_rejected_sources_used`, `claims_reference_registered_sources`,
  `claims_have_evidence_location`, `excerpt_length_within_policy` (≤ 400).
- **HypothesisGate**: `candidate_count` (≥ 3), `falsifiable`, `complete_fields`
  (independent + dependent variables, `expected_direction`,
  `supporting_claim_ids`), `recommended_exists`, `selected_exists`.
- **ExperimentGate**: `baselines_pre_registered`,
  `primary_secondary_metric_split` (both ≥ 1), `distance_constraints_declared`
  (`0 < detour_limit ≤ 0.30`), `stop_conditions_declared`,
  `input_snapshot_hashes`.
- **ResultGate** (over `reports/metrics_summary.json`): `module_provenance`
  ∈ `{module_outputs, offline_fixtures}`, `composite_not_sole_metric`
  (`metric_names` length ≥ 2), `negative_results_reported`
  (key `"negative_results"` present).
- **PublishGate** (over the WebPayload): `schema_version == "1.0"`,
  `selected_route_exists` (required when `status ∈ {supported, partially_supported}`;
  `route_id` must be in the catalog `route_ids` when that set is non-empty),
  `no_absolute_paths` (regex also catches Windows drive prefixes, Unix
  home-directory prefixes and `~/` — note it
  false-positives on bare `https://` in some positions, which is why
  `web_payload.references` deliberately has **no `url` field**),
  `no_sensitive_tokens` (`DASHSCOPE_API_KEY`, `Authorization:`, `sk-`),
  `references_https_or_local` (`https://` or `data/`, `local:`, `repository:`
  prefixes), `artifacts_relative_or_url`.
- **CitationGate**: `source_id_registered`, `evidence_location_present`,
  `verification_status_sufficient` (default min `verified`; `partial` also allowed
  when `quality_gates.evidence.min_verification_status == "partial"`),
  `numbers_traceable` (every number in `claim` must appear in `short_excerpt`
  or `evidence_location`, or equal `source.year`), `references_deduplicated`
  (by `doi:`/`pmid:`/`title:<normalized>:<year>`), `identifier_consistency`
  (<code>_DOI_RE = ^10\.\d{4,9}/\S+$</code>, <code>_PMID_RE = ^\d{1,12}$</code>). Plan-level:
  `references_deduplicated`, `reference_identifier_format`,
  `evidence_map_traceable`.
- **experiment_preregistration** (`experiment_design`, in-agent): the five checks
  `baselines_pre_registered`, `primary_secondary_metric_split`,
  `distance_constraints_declared`, `stop_conditions_declared`,
  `module_operations_whitelisted`.

`determine_support_status(summary)` reads `detour_pass_rate`,
`environment_win_rate`, `preference_win_rate`, `reference_verification_rate`,
`fatal_data_errors` (with `*_min` / `*_max` overrides from the `supported`
section; defaults `0.90 / 0.60 / 0.60 / 1.0`, fatal max `0`). Any rate `< 0.5`
→ `unsupported`.

### 6.3 Functional contract score (`generation/validation.py`)

`CONTRACT_THRESHOLD = 85`. `FunctionalContractReport` =
`{score: 0..100, threshold, passed, provenance, checks: [ContractCheck]}`;
`ContractCheck` = `{name, label, weight, earned, passed, critical, detail, evidence}`.
`passed = score >= 85 AND all critical checks passed`.

Weighted checks (name → weight, `critical` in bold):
`project_roots` 8, `environment_interface` 10, `route_generation` 10,
`evaluation_api` 12, `route_catalog_90` 12, **`map_web` 12**,
`core_interactions` 8, `local_launcher` 8, `tests_present` 8,
**`absolute_paths` 3**, **`sensitive_information` 5**, **`path_boundary` 2**,
**`path_traversal` 2**.

### 6.4 `checks/generated_quality.json` — exact shape

Written by `run_generated_quality_checks(context)` via
`store.write_json_atomic("checks/generated_quality.json", report.model_dump(mode="json"))`.
Model `GeneratedQualityReport` (`extra="forbid"`):

```jsonc
{
  "source_root": "<abs path of run_dir/workspace/source>",   // str, required
  "passed": true,                                            // bool, required
  "checks": [ /* GeneratedQualityCheck, required (default []) */ ],
  "report_path": "<abs path of run_dir/checks/generated_quality.json>"  // str, required
}
```

`GeneratedQualityCheck` (`extra="forbid"`):

```jsonc
{
  "name": "pytest:Qwen-Harness",
  "category": "pytest",        // Literal["pytest","ruff","pyright","node","evaluation_api","browser"]
  "status": "passed",          // Literal["passed","failed","not_run"]
  "passed": true,              // bool
  "required": true,            // bool, default true
  "command": ["uv","run",...], // list[str] | null
  "cwd": "<abs>",              // str | null
  "exit_code": 0,              // int | null
  "timed_out": false,          // bool, default false
  "stdout_path": "<abs>",      // str | null
  "stderr_path": "<abs>",      // str | null
  "error": null                // str | null
}
```

`passed = all(check.passed for check in checks if check.required)`.
**Exactly 14 checks, in this order** (`_PYTHON_PROJECTS` then `_ALL_PROJECTS`):

1. `pytest:Qwen-Harness` — `uv run --directory <src/Qwen-Harness> --frozen --extra dev pytest -q`, cwd = that project root, `command_id="generated.pytest.qwen-harness"`. Local failure `"<project>/tests 缺少 test_*.py"` if no `tests/**/test_*.py`.
2. `pytest:evaluation_model_qwen` — same argv shape, `command_id="generated.pytest.evaluation-model-qwen"`.
3. `pytest:weather_api_data` — `command_id="generated.pytest.weather-api-data"`.
4–11. `ruff:<project>` (`ruff check .`) and `pyright:<project>` (no extra args) for each of `Qwen-Harness`, `evaluation_model_qwen`, `weather_api_data`, `xuhui_route_builder` — argv `uv run --directory <project_root> --frozen --extra dev <tool> [check .]`, `command_id="generated.ruff.<label>"` / `"generated.pyright.<label>"` where `<label>` = project name lowercased with `_`→`-`. (Unit test asserts `len(static_specs) == 8` and every one has `--directory`.)
12. `Node 契约测试` — category `node`, `command_id="generated.node_contract"`, argv `["node","--test", <posix-relative paths of sorted xuhui_route_builder/tests/*.test.mjs>]`, cwd = `source_root`. Local failure `"xuhui_route_builder/tests 缺少 *.test.mjs"` (then `command is None`).
13. `评价 API 健康检查` — category `evaluation_api`, `command_id="generated.evaluation_api_health"`, cwd = `<source_root>/evaluation_model_qwen`, argv `["uv","run","--project",".","--frozen","python","-c", _API_HEALTH_SCRIPT]` where

    ```python
    _API_HEALTH_SCRIPT = (
        "from fastapi.testclient import TestClient; "
        "from evaluation_model_qwen.api import app; "
        "response=TestClient(app).get('/api/v1/health'); "
        "assert response.status_code == 200, response.text; "
        "payload=response.json(); "
        "assert payload.get('status') in {'ok', 'healthy'}, payload"
    )
    ```
14. `真实浏览器验收` — category `browser`, **must be `checks[-1]`**, `command_id="generated.browser_gate"`, cwd = `<source_root>/xuhui_route_builder`, `timeout_seconds=180`, `writes=[<run>/checks/browser]`, argv:

    ```
    uv run --with playwright==1.55.0 python <harness_root>/scripts/generated_browser_gate.py
      --source-root <run>/workspace/source
      --output-dir  <run>/checks/browser
      --reference-url https://zion-johnson99.github.io/AI_Scientist_shanghai_route/
    ```

`_validate_roots` raises `InputContractError` unless all four project dirs exist
under `workspace/source` **and** `<harness_root>/pyproject.toml` exists; it raises
`PathBoundaryError` if `source_root` resolves outside the run dir.
Every `CommandSpec.cwd` must resolve inside `workspace/source`, and every
`argv[0]` must be `uv` or `node` (unit-test assertions).

`final_validation` promotes this report into the gate via
`_generated_quality_gate`: only `required` checks become `GateCheck`s named
`f"generated_{check.category}_{check.name}"` (e.g.
`generated_pytest_pytest:evaluation`, `generated_browser_真实浏览器验收`),
`gate="generated_project_quality"`, `passed=report.passed`.

`final_validation` also adds `GateCheck(name="generated_project_functional_score",
passed = float(project_generation.score) >= 85.0 and project_generation.passed is True)`.
Offline runs skip `run_generated_quality_checks` entirely (warning
`"离线 fixture 跳过生成工程可执行质量检查"`).
If the browser check fails with `"AssertionError:"` in its diagnostics, the engine
runs exactly one targeted Qwen repair (`_repair_failed_browser_once`) then re-runs
`run_generated_browser_check` and rewrites `checks/generated_quality.json`.
Repair target selection: layout markers (`横向溢出`, `地图宽度`, `地图高度`,
`地图不可见`, `工作台不可见`) → `xuhui_route_builder/web/styles/main.css`
(check `browser_visual_contract`); interaction markers (`环境详情`,
`data-testid=route-card`, `路线数量`, `筛选`, `同步到地图`, `控制台错误`,
`资源请求失败`) → `xuhui_route_builder/web/src/main.js`
(check `browser_interaction_contract`); otherwise →
`xuhui_route_builder/web/index.html` (check `browser_dom_contract`).

---

## 7. Adapter data contracts (all paths relative to `<run>/workspace/source`)

`GeneratedProjectPaths.from_context`:
`source_root = <run>/workspace/source`,
`web_data_root = <source_root>/xuhui_route_builder/data/web`,
`route_catalog_path = <web_data_root>/route_catalog.json`,
`environment_dashboard_path = <web_data_root>/environment_dashboard.json`.
Every path is boundary-checked inside `source_root`.
`WorkflowContext.generated.module_paths`:

```python
{"route": "xuhui_route_builder",
 "environment": "weather_api_data",
 "evaluation": "evaluation_model_qwen",
 "web": "xuhui_route_builder/web"}
```

### 7.1 route (`adapters/route_builder.py`)
`EXPECTED_ROUTE_COUNT = 90`, `EXPECTED_PER_MODE = 30`, `MODES = ("walk","run","bike")`.
- `CATALOG_RELATIVE = "data/web/route_catalog.json"` — **top-level JSON array** of
  exactly 90 objects; each needs `route_id: str`, `route_mode ∈ MODES`,
  `route_name`, `validation_status`, `geometry_status` (all truthy); no duplicate
  `route_id`; 30 per mode; warning if `validation_status != "accepted"`.
- `GEOMETRY_RELATIVE = "data/web/xuhui_routes.geojson"` — `FeatureCollection` with
  90 features; `features[].properties.route_id`; `geometry.type == "LineString"`
  with ≥ 2 valid `[lon, lat]` points; the id set must match the catalog exactly.
- Optional (warning only if missing): `data/web/xuhui_entries.geojson`,
  `data/web/poi_catalog.json`, `data/web/access_cases.json`.
- `supported_operations = ("route.read_snapshot", "route.validate_seeds", "route.validate_routes")`.

### 7.2 environment (`adapters/environment_data.py`)
`data/web/environment_dashboard.json` — top-level **object** with keys
`metadata`, `current`, `forecast`, `routes`:
- `metadata.generated_at` parseable ISO; `metadata.status`, `current.status`,
  `forecast.status`, `routes.status` ∈ `STATUS_ENUM = {ok, partial, stale, no_data, error}`.
- `routes.items`: list of **exactly 90** objects with unique `route_id`;
  `routes.count == len(routes.items)`.
- Each item needs `pm2_5` (dict), `noise` (dict), `pollen_daily` (dict or list of dicts).
- Each metric block: `status ∈ STATUS_ENUM`, `estimated: bool`, `unit` non-empty str
  (expected: `pm2_5` → `"µg/m³"`, `noise` → `"0-100 risk index"`,
  `pollen` → `"0-100 risk index"`), `business_time` either `"static_scenario"` or a
  parseable / 10-char date.
- Cross-check of `route_id`s against the route catalog: missing/extra → **errors**.
- `EXPORT_RELATIVES` under `weather_api_data/runtime/exports/` (missing → warning only):
  `environment_latest.json`, `environment_hourly.json`,
  `grid_environment_latest.json`, `pollen_grid_scores.json`, `noise_segments.json`,
  `route_environment.json`.
- `supported_operations = ("environment.read_snapshot", "environment.refresh")`.

### 7.3 evaluation (`adapters/evaluation_model.py`)
Preflight requires, inside the generated tree:
- the `evaluation_model_qwen` module dir;
- `INTERNAL_SCORE_SCRIPT = "src/qwen_harness/adapters/evaluation_score_candidates.py"`
  (i.e. `<source_root>/Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py`);
- `evaluation_model_qwen/config/default_weights.json` with keys `goal_weights`,
  `environment_weights`, `risk_thresholds`, `status_reliability`;
- `route_catalog.json` and `environment_dashboard.json` (from 7.1 / 7.2).

Execution runs the score script through `uv`; `_score_command_argv` puts
`str((run_dir / "workspace/source/evaluation_model_qwen").resolve())` at `argv[3]`
and a path ending in `evaluation_score_candidates.py` at `argv[5]`;
`command_id = f"evaluation.score_candidates.{safe_label(parameters['label'], 'run')}"`.
CLI contract of that script:
`python <script> --profile <json> --weights <json> --route-catalog <json> --environment-dashboard <json>`;
stdout must be **one** JSON object; exit code 2 on error.

stdout contract (`CandidateExportResult`, `extra="forbid"`):
`profile: dict`, `risk: dict`, `data_generated_at: datetime`,
`candidate_count: int (>= 0, == len(candidates))`, `candidates: list`,
`weights_sha256: str` (non-empty). `risk.status == "paused"` → empty candidates.
`profile.target_time == "now"` → resolved to Asia/Shanghai ISO.
Imports it relies on: `evaluation_model_qwen.loaders.load_data`,
`models.UserProfile`, `scoring.evaluate_risk`, `scoring.score_routes`,
`service.evaluation_root`, `service.load_weights`.

Adapter writes one cell per registered variant:
`experiments/score_candidates/<case_id>__<variant_id>.json`
(`CELLS_DIR = "experiments/score_candidates"`), body = stdout payload plus
`case_id` and `variant_id`. The profile input is written to
`modules/evaluation/<safe_label>_input.json`. `data_hashes = {"weights_sha256": ...}`.
Offline fixture cell candidate shape:
`{route:{route_id, route_name, route_mode, distance_m}, access_distance_m: 120.0,
base_score: 0.75, data_confidence: 0.8, matched_preferences, dimension_scores,
environment_summary:{pm2_5:{value}, noise:{value}, pollen:{value}}}`,
`provenance = "offline_fixtures"`.

`VARIANT_IDS` (frozen order, `config/experiment_variants.json` must declare
**exactly** these five in this order):
`B0_shortest_feasible`, `B1_pm25_only`, `B2_multi_environment`,
`B3_non_personalized`, `M1_personalized_constrained`.
`DIMENSION_NAMES` = `environment_health`, `sport_match`, `access_convenience`,
`route_quality`, `interest_service`.
`exposure_risk_coefficients` = `{alpha_pm25: 0.5, beta_noise: 0.3, gamma_pollen: 0.2}`;
`distance_constraints` = `{detour_ratio_max_default: 0.2, target_deviation_max_default: 0.15}`.

`PRESET_CASES` case_ids (`experiments/profiles.py`) — 10 cases:
`XH-WALK-HEALTH-AIR`, `XH-WALK-SCENERY-WATERFRONT`, `XH-WALK-NEARBY-NOISE`,
`XH-WALK-BALANCED-POLLEN`, `XH-RUN-HEALTH-AIR-NOISE`, `XH-RUN-BALANCED-LOOP`,
`XH-RUN-SCENERY-WATERFRONT`, `XH-BIKE-NEARBY-CONVENIENCE`, `XH-BIKE-HEALTH-PARK`,
`XH-BIKE-SCENERY-LONG`.

### 7.4 web (`adapters/web_product.py`)
`PAYLOAD_RELATIVE = "publish/research_harness_latest.json"` (run-relative).
Preflight checks `route_catalog.json`, `environment_dashboard.json`,
`web/index.html`; **≥ 3 warnings becomes an error**.
`audit_payload` requires `schema_version == "1.0"`, `status ∈ SupportStatus`,
full `WebPayload` validation, plus `audit_payload_text` on the serialized JSON:
forbidden secret markers `api_key`, `apikey`, `api-key`, `dashscope_api_key`,
`access_token`, `secret`, `"bearer "`, `sk-`, `private_key`; forbidden Windows
drive paths `[A-Za-z]:[\\/]`; forbidden POSIX home dirs
`/(home|Users|mnt|opt|var|tmp)/` or `~/`; forbidden reasoning-key markers
`reasoning`, `thinking`, `chain_of_thought`, `raw_completion`, `raw_response`
(matched as `` `"marker`` ).

### 7.5 experiment_analysis consumers
`experiments/experiment_results.json` payload keys:
`schema_version`, `run_id`, `generated_at`, `provenance`, `profiles`,
`plan` = `{hypothesis_id, variants, detour_limit, target_distance_tolerance}`,
`variants_registry`, `module_statuses`, `data_hashes` = `{modules, weights_sha256}`,
`cells`, `metrics_summary`.
Cell statuses: `ready`, `no_candidate`, `paused`, `missing`, `invalid`
(`CELL_STATUS_*`). `REQUIRED_CELL_KEYS = ("profile","risk","candidates")`.
Ready cells carry `chosen` = `{route_id, route_name, distance_m, access_distance_m,
base_score, data_confidence, matched_preferences, dimension_scores,
environment_summary}`, `metrics` (13 keys incl. `env_risk`, `preference_hit_rate`,
`target_deviation`, `data_reliability`, `composite_score`), `dimension_scores`,
`constraints` = `{target_deviation, target_ok, access_ok, detour_ratio, detour_ok,
constraint_pass}`, `selection_gate_passed`, `messages`.

`metrics_summary.json` (identical at `experiments/` and `reports/`) keys:
`schema_version="1.0"`, `run_id`, `generated_at`, `provenance`, `metric_names`
(the 11 `_METRIC_NAMES`), `cells_total`, `cell_status_counts`,
`no_candidate_rate`, `constraint_pass_rate`, `detour_pass_rate`,
`environment_win_rate`, `preference_win_rate`, `reference_verification_rate`,
`fatal_data_errors`, `mean_data_reliability_m1`, **all `supported` threshold keys
spliced in**, `comparisons` = `{<variant>: {env_risk: {m1_or_variant_mean, b0_mean,
paired}, preference_hit_rate: {...}}}`, `negative_results` =
`{no_candidate_cells, missing_cells, paused_cells, invalid_cells}`,
`module_statuses`, `support_status`.
`paired` = `{pairs, mean_difference, median_difference, win:{wins,ties,losses,pairs,rate},
differences_summary:{n,mean,median,iqr}, ci_95, seed:1234, iterations:2000}`.
`provenance` = `"offline_fixtures"` if offline else `"module_outputs"`.

---

## 8. Web payload exact shape (`publish/research_harness_latest.json`)

Written by `reporting/web_payload.py` `stage_handler` with
`PAYLOAD_RELATIVE = "publish/research_harness_latest.json"`.

```jsonc
{
  "schema_version": "1.0",
  "run_id": "<run-id>",
  "generated_at": "<ISO-8601 UTC>",
  "status": "supported|partially_supported|unsupported|inconclusive|error",
  "research_question": "<goal.question or goal.title>",
  "hypothesis": "<selected hypothesis statement>",
  "selected_route": { "route_id": "...", "route_name": "...",
                      "reason": "当前候选集中的约束最优路线" } ,   // or null
  "key_metrics": [ { "metric_id": "...", "label": "...", "value": <4dp>,
                     "unit": "...", "direction": "higher|lower" } ],
  "baseline_comparison": [ { "baseline_id": "...", "name": "...",
                             "metric_id": "...", "value": ..., "delta": ... } ],
  "iterations": [ { "iteration": "iteration-1", "status": "...", "reason": "..." } ],
  "references": [ { "source_id": "...", "title": "...", "year": ... } ],  // NO url field
  "limitations": [ "<5 fixed SCIENTIFIC_BOUNDARIES strings>", "<negative-result notes>" ],
  "artifacts": [
    "reports/scientific_plan.json",
    "reports/scientific_plan.md",
    "reports/experiment_report.md",
    "reports/reproducibility.md",
    "experiments/experiment_results.json",
    "experiments/metrics_summary.json"
  ]
}
```

`SELECTED_ROUTE_REASON = "当前候选集中的约束最优路线"`.
`METRIC_LABELS` keys: `detour_pass_rate` (绕路约束通过率, 比例, higher),
`environment_win_rate` (环境改善胜率（M1 vs B0）), `preference_win_rate`
(偏好命中率胜率（M1 vs B0）), `constraint_pass_rate`, `no_candidate_rate` (lower),
`mean_data_reliability_m1`. Values rounded to 4 decimals.
`selected_route` comes from `experiments/experiment_results.json` →
`cells[]` where `variant_id == "M1_personalized_constrained"` and
`status == "ready"` → `chosen.route_id`; skipped unless that id is present in the
route catalog ids. `baseline_comparison` comes from
`summary.comparisons[variant].{env_risk, preference_hit_rate}.{m1_or_variant_mean, b0_mean}`.
`iterations` from `iterations/iteration-*/decision.json`.
`references` only from `verification_status == "verified"` sources.
`status` = `conclusion_status` / `state.final_support_status`, else
`determine_support_status(summary)`, else `"inconclusive"`.
The handler also calls `markdown.generate_report_artifacts(context)`, producing
`reports/scientific_plan.md`, `reports/experiment_report.md`,
`reports/reproducibility.md`.

`local_publish` later **moves** the staged payload to
`publish/local-product/data/web/research_harness_latest.json`
(`WEB_PAYLOAD_NAME = "research_harness_latest.json"`); after a successful publish
`publish/research_harness_latest.json` no longer exists.

---

## 9. Browser gate (`scripts/generated_browser_gate.py`)

Invocation (see §6.4 item 14). The script serves
`<source_root>/xuhui_route_builder` with `ThreadingHTTPServer` +
`_QuietHandler`, navigates to `{base}/web/`, and launches
`playwright.chromium.launch(channel="chrome", headless=True)`.

`VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}`.

Pass criteria, per viewport (`_exercise_viewport`):
1. `[data-testid="route-card"]` first element `state="visible"` within `5_000` ms,
   else `AssertionError(f"{name}: data-testid=route-card 未在 5 秒内出现")` and a
   `local-<name>-failure.png`.
2. `[data-testid="map"]` `is_visible()` — `"{name}: 地图不可见"`.
3. `[data-testid="route-workbench"]` `is_visible()` — `"{name}: 路线工作台不可见"`.
4. `map.bounding_box()` not `None`; `width >= 320` (desktop) / `260` (mobile);
   `height >= 300` (desktop) / `220` (mobile).
5. `route_cards.count() == 90`.
6. `document.documentElement.scrollWidth - window.innerWidth <= 1`.
7. `[data-testid="mode-filter"]` `.select_option("walk")` (must be a `<select>`
   with an option whose value is `walk`) → after 200 ms `route_cards.count() == 30`.
8. Click `route_cards.first` → `[data-testid="environment-details"]` visible
   within `5_000` ms, and its `inner_text()` contains all of `"PM2.5"`, `"噪声"`, `"花粉"`.
9. `map.get_attribute("data-selected-route-id")` truthy.
10. No local HTTP response with `status >= 400` from `base_url`.
11. No console `error` messages and no `pageerror`s.

Selectors required in the generated DOM: `data-testid="map"`,
`data-testid="route-workbench"`, `data-testid="route-card"`,
`data-testid="mode-filter"`, `data-testid="environment-details"`,
`data-testid="recommendation-button"` (the last one is required by the delivery
contract / functional validator, not asserted by the browser script).

Output `<run>/checks/browser/browser_acceptance.json`:

```jsonc
{
  "passed": true,
  "reference_url": "https://zion-johnson99.github.io/AI_Scientist_shanghai_route/",
  "viewports": {
    "desktop": { "viewport": {"width":1440,"height":900}, "route_count": 90,
                 "walk_route_count": 30, "map_box": {...},
                 "selected_route_id": "...",
                 "environment_markers": ["PM2.5","噪声","花粉"],
                 "horizontal_overflow_px": 0,
                 "screenshot": "<abs>/local-desktop.png" },
    "mobile":  { ... }
  },
  "reference_screenshots": { "desktop": "...online-desktop.png", "mobile": "..." },
  "reference_error": "<only if the online reference could not be captured>",
  "error": "<only on failure>"
}
```

Screenshots: `local-<name>.png`, `local-<name>-failure.png`, `online-<name>.png`.
CLI: `--source-root` (required), `--output-dir` (required), `--reference-url`
(required). Exit code `0` on pass. Reference-capture failure never fails the run
(it only records `reference_error`).

---

## 10. Tests, linters, type checker — exact commands

Harness toolchain (`Qwen-Harness/pyproject.toml`): `requires-python = ">=3.10"`;
dependencies `openai>=2.0,<3`, `pydantic>=2.0,<3`, `python-dotenv>=1.0,<2`,
`requests>=2.31,<3`, `pypdf>=6.0,<7`, `PyYAML>=6.0,<7`;
`[project.optional-dependencies] dev = ["pytest>=8.0","pyright>=1.1.411","ruff>=0.16.3"]`;
console script `qwen-harness = "qwen_harness.cli:main"`.
`[tool.pytest.ini_options] pythonpath = ["src"]`, `testpaths = ["tests"]`.
`[tool.ruff] line-length = 100`; `lint.select = ["E4","E7","E9","F","I","BLE","RUF","TRY"]`;
`lint.ignore = ["RUF001","RUF002","RUF003","TRY003","TRY301"]`;
`lint.isort.known-first-party = ["qwen_harness"]`.
`[tool.pyright] include = ["tests"]`, `extraPaths = ["src"]`,
`pythonVersion = "3.10"`, `typeCheckingMode = "basic"`,
`reportMissingTypeStubs = false`, `reportPrivateUsage = false`.

CI (`.github/workflows/qwen-harness-ci.yml`, job `offline-quality-gate`,
`working-directory: Qwen-Harness`, env `QWEN_HARNESS_NETWORK_ENABLED="false"`,
`QWEN_HARNESS_RUNTIME_ROOT="runtime"`):

```
uv sync --all-extras --frozen
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright --project pyproject.toml
uv run qwen-harness validate --scope config
uv run qwen-harness run --goal-file examples/goals/multisource-route.json \
    --workflow reproduce-existing --offline --approval-mode auto --max-iterations 1 --json
```

Per-generated-project commands issued by the harness (must succeed inside
`workspace/source/<project>`; each project therefore needs its own
`pyproject.toml` with a `dev` extra providing pytest/ruff/pyright and a
`uv.lock`, because `--frozen` is used):

```
uv run --directory <project> --frozen --extra dev pytest -q
uv run --directory <project> --frozen --extra dev ruff check .
uv run --directory <project> --frozen --extra dev pyright
node --test xuhui_route_builder/tests/*.test.mjs        # cwd = workspace/source
uv run --project . --frozen python -c "<_API_HEALTH_SCRIPT>"   # cwd = evaluation_model_qwen
uv run --with playwright==1.55.0 python scripts/generated_browser_gate.py ...
```

Existing harness test suite and the assertions that constrain generated code:

- `tests/unit/test_generated_quality.py` — `report.passed is True`;
  required categories == `{pytest, ruff, pyright, node, evaluation_api, browser}`;
  `checks[-1].category == "browser"` and `passed/required is True`; every
  `spec.cwd` inside `workspace/source`; every `argv[0] ∈ {"uv","node"}`;
  browser argv starts `["uv","run","--with","playwright==1.55.0"]` and contains
  `--source-root` / `--output-dir`; `len(static_specs) == 8` all containing
  `--directory`; saved `checks/generated_quality.json` has `passed is True` and
  `source_root == str(<resolved workspace/source>)`; a failing ruff yields
  `status="failed"`, `exit_code == 1`, non-null `stderr_path`, and
  `len(runner.specs) == 14`; a missing `*.test.mjs` yields `node.status="failed"`,
  `node.command is None`, `"*.test.mjs" in node.error`.
- `tests/contracts/test_cli_contracts.py` — parser keeps
  `run/--goal/--workflow/--offline/--approval-mode`; blank goal → exit code `2`
  and JSON `{"ok": false, "error": {"error_type": "input_contract_error"}}`;
  score-script parser exposes `--profile/--weights/--route-catalog/--environment-dashboard`;
  missing generated evaluation module → `RuntimeError` matching
  `"当前 run 生成的评价模块"`; `_score_command_argv` has no
  `"evaluation-model-qwen"` entry, `argv[3]` = resolved
  `workspace/source/evaluation_model_qwen`, `argv[5]` ends with
  `evaluation_score_candidates.py`; `_validate_contract` returns `[]` for the exact
  payload and an error containing `"candidates 数量"` on count mismatch;
  `_write_candidate_cells` returns exactly
  `["experiments/score_candidates/P01__B0_shortest_feasible.json",
    "experiments/score_candidates/P01__M1_personalized_constrained.json"]`.
- `tests/unit/test_generation_validation.py` — offline fixture scores `>= 85`,
  `checks/generation_contract.json` `passed is True`, `provenance ==
  OFFLINE_FIXTURE_PROVENANCE ("offline_fixture")`; `workspace/architecture.json`,
  `workspace/generation_result.json`,
  `stages/project_generation/model_audits.json` all exist; a file containing
  `api_key = "sk-live-..."` forces `sensitive_information` and `passed is False`;
  an empty four-dir tree scores `< 85` and reports at least
  `{environment_interface, route_generation, evaluation_api, route_catalog_90,
  map_web, local_launcher, tests_present}`; `web/src/main.js` loading
  `data/web/` from a non-module entry triggers `map_web`;
  `"C:\\Users\\..."` and `open("../outside.txt")` trigger `absolute_paths` and
  `path_traversal`; `https://unpkg.com/...` and a test asserting on
  `"C:\\Users\\"` do **not** trigger `absolute_paths`;
  `build_generation_requirements` must contain the four `__init__.py` paths,
  `xuhui_route_builder/pyproject.toml`, `1440x900`, `390x844`,
  `data-testid=map`, `data-testid=route-card`, `data-testid=environment-details`,
  `PM2.5、噪声、花粉`, the reference URL, and stay under `12_000` chars;
  `_materialize_generated_data` must produce the three `data/web` JSONs;
  the offline generated fixture must satisfy **all four** adapter preflights with
  `status != "error"`.
- `tests/unit/test_local_publish.py` — see §11.
- `tests/integration/test_project_config.py` — `validate_all_configs(HARNESS_ROOT) == []`.
- Also present: `tests/unit/{test_adapter_project_paths, test_config,
  test_experiment_plan_contract, test_generation_engine, test_llm_client,
  test_paths, test_runtime_generated_repair, test_subprocess_runner}.py`;
  `tests/e2e/` is currently empty.

CLI: `qwen-harness doctor | run | resume | publish | status | report | list-runs | validate --scope {config,skills,adapters,runs,all}`.
Exit codes: `0` success or paused-for-approval, `1` gate failed / unsupported /
approval rejected, `2` config-input-path-skill contract error, `3` model or source
unavailable, `4` module command failure, `5` corrupted/interrupted run.

---

## 11. Publish expectations (`publish_web` → `reporting/local_publish.py`)

Constants:

```python
REQUIRED_SOURCE_MODULES = ("Qwen-Harness","evaluation_model_qwen","weather_api_data","xuhui_route_builder")
REPORT_PUBLISH_NAMES = {"full_run_report.md": "完整运行报告.md",
                        "scientific_plan.md": "科学计划.md",
                        "experiment_report.md": "实验报告.md"}
WEB_PAYLOAD_NAME = "research_harness_latest.json"
EXCLUDED_GENERATED_PARTS = {".git",".mypy_cache",".pytest_cache",".ruff_cache",
                            ".venv","__pycache__","node_modules","runtime","test-results"}
SENSITIVE_FILENAMES = {".env","local-amap-config.js","local-tencent-config.js"}
SENSITIVE_NAME_PARTS = ("credential","secret","token")
```

Preconditions (all raise before `publish/` is replaced):
- `workspace/source` exists and has ≥ 1 publishable file; each of the four
  `REQUIRED_SOURCE_MODULES` sub-trees likewise (`FileNotFoundError` naming the module).
- `workspace/source/xuhui_route_builder/web/index.html` exists
  (`"本轮生成网页入口不存在"` → matched by test as `"网页入口"`).
- `web/` and `data/web/` trees each have ≥ 1 publishable file.
- `reports/full_run_report.md`, `reports/scientific_plan.md`,
  `reports/experiment_report.md` all exist (`"本轮生成报告 <中文名> 不存在"`,
  matched by test as `"实验报告"`).
- Staged `publish/research_harness_latest.json`, if present, must parse as a JSON
  **object** (`ValueError` matching `"web_payload JSON 无效"`), and must not be a symlink.
- No symlink anywhere in the generated tree (`ValueError`).

Resulting tree (test asserts `publish/` contains **exactly** these names):
`checks`, `launch-local.ps1`, `local-product`, `reports`, `source`,
`source_manifest.json`.
- `publish/source/<module>/**` — copies of `workspace/source/<module>` only
  (repository modules are never read; test asserts no `repository-only.txt`).
- `publish/local-product/web/**` — copy of generated `web/`.
- `publish/local-product/data/web/**` — copy of generated `data/web/`, plus the
  staged payload written to `local-product/data/web/research_harness_latest.json`.
- `publish/reports/{完整运行报告.md, 科学计划.md, 实验报告.md}`.
- `publish/checks/**` — copy of run `checks/`; if `checks/` is absent, a
  `checks_summary.json` with `{run_id, status:"not_recorded", message}`.
- `publish/source_manifest.json`:

  ```jsonc
  { "schema_version": "1.0",
    "source_origin": "workspace/source",
    "source_file_counts": { "<module>": <int>, ... },
    "file_count": <int>,
    "files": [ { "path": "<posix relative to publish/>", "size_bytes": <int>, "sha256": "<hex>" } ] }
  ```
  (excludes itself; must contain entries `reports/完整运行报告.md` and
  `local-product/data/web/research_harness_latest.json`).
- `publish/launch-local.ps1` — written with `encoding="utf-8-sig"`; body is the
  frozen `LAUNCH_SCRIPT`. Required substrings (unit-tested):
  `source\evaluation_model_qwen`, `uvicorn`, `evaluation_model_qwen.api:app`,
  `8124/api/v1/health`, `缺少 pyproject.toml`, `健康检查未就绪`, `Write-Warning`,
  `网页继续以无推荐服务模式启动`, `Get-NetTCPConnection`,
  <code>$apiServiceProcessId</code>, `http.server 8130`; and it must **not** contain
  `evaluation-model-qwen-api`.
  Behaviour: verifies `local-product/web/index.html` and
  `source/evaluation_model_qwen/pyproject.toml`; sets
  `EVALUATION_MODEL_QWEN_OFFLINE=1`,
  `EVALUATION_MODEL_QWEN_ALLOWED_ORIGINS="http://127.0.0.1:8130,http://localhost:8130"`,
  `EVALUATION_MODEL_QWEN_AUDIT_ROOT=<apiRoot>/runtime/recommendations`;
  starts `uv run --project <apiRoot> uvicorn evaluation_model_qwen.api:app --host 127.0.0.1 --port 8124`
  (logs to `checks/local-api.stdout.log` / `.stderr.log`), polls health up to
  120 × 500 ms, then `python -m http.server 8130 --bind 127.0.0.1 --directory local-product`;
  web UI at `http://127.0.0.1:8130/web/`; on exit kills <code>$apiServiceProcessId</code>
  and <code>$apiProcess</code>.
- `publish/published.flag` = `{"target": "publish/local-product", "run_id": ..., "local_url": ...}`.
- `build_local_publish` returns `{publish_root, local_url, source_origin,
  source_file_counts, manifest}`.
- `refresh_local_publish_metadata` re-runs `_prepare_full_report`, re-copies the
  three Chinese reports and rewrites `source_manifest.json` preserving
  `source_file_counts`.

So the generated tree must contain, at minimum, these publishable files:
`Qwen-Harness/launch-local.ps1` **and** a `pyproject.toml` (test fixture uses
`pyproject.toml` as the single publishable file per module — `source_file_counts["Qwen-Harness"] == 1`
in that fixture; real runs will have many), plus
`evaluation_model_qwen/pyproject.toml` (required by the launcher).

---

## 12. Conformance checklist (top 30)

1. All 19 `full-research` stages exist in order, with the exact handler strings of §4; `module_execution.approval == "critical"`, `publish_web.approval == "always"`.
2. Every run dir has `inputs/research_goal.json`, `inputs/run_options.json`, `run_manifest.json`, `state.json` — otherwise `load_run` fails.
3. `run_manifest.module_write_enabled` is `false`; `schema_version` is `"1.0"`.
4. `run_id` matches <code>^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$</code>.
5. All JSON artifacts are `indent=2, ensure_ascii=False` + trailing newline, written atomically.
6. Every stage output validates against its Pydantic model with `extra="forbid"` — no unknown keys anywhere.
7. `EvidenceClaim.evidence_location` is non-empty for every claim; `short_excerpt` ≤ 400 chars; every `source_id` is registered and `verification_status == "verified"`.
8. ≥ 5 verified sources and `reference_verification_rate == 1.0`; no `rejected` source is referenced.
9. Every number appearing in a `claim` also appears in `short_excerpt`/`evidence_location` or equals `source.year`.
10. ≥ 3 hypothesis candidates, each falsifiable with independent + dependent variables, `expected_direction`, and `supporting_claim_ids` that all exist; `recommended_hypothesis_id` and `selected_hypothesis_id` are in the candidate set.
11. `ExperimentPlan`: `0 < detour_limit ≤ 0.30`, `target_distance_tolerance > 0`, ≥ 1 baseline, ≥ 1 primary **and** ≥ 1 secondary metric, non-empty `stop_conditions`, and every `operation_id` in `ALLOWED_OPERATION_IDS`.
12. `ExperimentPlan.variants` ⊆ the five frozen `VARIANT_IDS`; `config/experiment_variants.json` declares exactly those five in order with `schema_version == "1.0"`.
13. `workspace/source` contains all four project roots: `Qwen-Harness`, `evaluation_model_qwen`, `weather_api_data`, `xuhui_route_builder`.
14. All 16 `delivery_contract.required_files` exist (see §5.8 / stage_handlers list), including `Qwen-Harness/launch-local.ps1`, `Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py`, `evaluation_model_qwen/config/default_weights.json`, `xuhui_route_builder/tests/visual_contract.test.mjs`.
15. `checks/generation_contract.json` has `score >= 85`, `passed == true`, and all critical checks (`map_web`, `absolute_paths`, `sensitive_information`, `path_boundary`, `path_traversal`) passed.
16. `route_catalog.json` is a top-level array of exactly 90 items, 30 each for `walk`/`run`/`bike`, each with `route_id`, `route_name`, `route_mode`, `validation_status`, `geometry_status`, no duplicate ids.
17. `xuhui_routes.geojson` is a `FeatureCollection` with exactly 90 `LineString` features (≥ 2 valid `[lon, lat]` each) whose `properties.route_id` set equals the catalog's.
18. `environment_dashboard.json` is an object with `metadata`/`current`/`forecast`/`routes`; all four `status` fields ∈ `{ok, partial, stale, no_data, error}`; `metadata.generated_at` parseable ISO.
19. `routes.items` has exactly 90 entries with unique `route_id` matching the catalog, `routes.count == 90`, each item having `pm2_5`, `noise`, `pollen_daily` blocks with `status`, `estimated`, `unit`, `business_time`.
20. `evaluation_model_qwen` exposes `loaders.load_data`, `models.{RiskAssessment, ScoredRoute, StrictModel, UserProfile}`, `scoring.{evaluate_risk, score_routes}`, `service.{evaluation_root, load_weights}`, and a FastAPI `app` with `/api/v1/health` returning `status ∈ {"ok","healthy"}` plus `/api/v1/recommendations`.
21. The score script accepts `--profile --weights --route-catalog --environment-dashboard` and prints exactly one JSON object with `profile`, `risk`, `data_generated_at`, `candidate_count == len(candidates)`, `candidates`, non-empty `weights_sha256`; exits `2` on error.
22. One cell file per case × variant at `experiments/score_candidates/<case_id>__<variant_id>.json`, each carrying top-level `case_id` and `variant_id`.
23. Each of the four generated projects passes `pytest -q` (needs `tests/**/test_*.py` in `Qwen-Harness`, `evaluation_model_qwen`, `weather_api_data`), `ruff check .`, and `pyright` under `uv run --frozen --extra dev` — so each needs a `pyproject.toml` with a `dev` extra and a `uv.lock`.
24. `xuhui_route_builder/tests/*.test.mjs` exists and passes `node --test`.
25. Web page: `data-testid` values `map`, `route-workbench`, `route-card`, `mode-filter`, `environment-details`, `recommendation-button`; `mode-filter` is a `<select>` with a `walk` option; initial 90 cards → 30 after `walk`; clicking a card shows `environment-details` containing `PM2.5`, `噪声`, `花粉`; `map` gets a non-empty `data-selected-route-id`; no horizontal overflow > 1 px at 1440×900 and 390×844; no console/page errors; no local HTTP ≥ 400; data loaded via `../data/web/` or `/data/web/`; ES-module entry (`type="module"` script whose src matches `main|app.js`).
26. `checks/generated_quality.json` matches `GeneratedQualityReport` exactly (`source_root`, `passed`, `checks`, `report_path`), has all 14 checks with `browser` last, and `passed == true`.
27. `reports/scientific_plan.json` exists and validates as `ScientificPlan` (required: `run_id`, `problem_statement`, `rationale`, `datasets`, `paper_title`, `paper_abstract`, `experiments`); its `references` use only verified sources and pass `reference_identifier_format` + `references_deduplicated`; `evidence_map` values are known `claim_id`s.
28. `reports/metrics_summary.json` exists with `provenance ∈ {module_outputs, offline_fixtures}`, `metric_names` length ≥ 2, and a `negative_results` key (ResultGate).
29. `publish/research_harness_latest.json` validates as `WebPayload`, `schema_version == "1.0"`, `status` a legal `SupportStatus`, `selected_route` present when status is `supported`/`partially_supported` with a `route_id` from the catalog, no absolute paths, no `DASHSCOPE_API_KEY`/`Authorization:`/`sk-`, no reasoning-key markers, references https-or-local, artifacts run-relative; `references` entries must not include a `url` field.
30. `reports/{full_run_report.md, scientific_plan.md, experiment_report.md, reproducibility.md}` all exist before `publish_web`; the generated tree has no symlinks and no `.env` / `local-amap-config.js` / `local-tencent-config.js` / `*credential*` / `*secret*` / `*token*` files; `evaluation_model_qwen/pyproject.toml` exists so `launch-local.ps1` can start uvicorn.

### Extra notes worth honouring [inferred]

- `module_data_hashes` in the manifest is computed from the **repository** route and
  environment module data roots (`paths.route_module`, `paths.environment_module`);
  missing files degrade to a warning, not an error.
- `derived_config.json` is a merged dict; feedback actions may patch `weights` and
  `detour_limit` only — source config files are never modified.
- Offline (`reproduce-existing`) stage fixtures live at
  `examples/fixtures/model-responses/<stage>.json` and are mapped by
  `OFFLINE_FIXTURE_MODELS`: `problem_framing→ProblemFrame`,
  `source_collection→SourceRecord`, `evidence_extraction→EvidenceCard`,
  `gap_analysis→KnowledgeGapSet`, `hypothesis_generation→HypothesisSet`,
  `hypothesis_critique`/`hypothesis_selection→HypothesisReview`,
  `experiment_design→ExperimentPlan`, `experiment_analysis→ResultInterpretation`,
  `feedback_decision→IterationDecision`, `scientific_report→ScientificPlan`,
  `web_payload→WebPayload`. Offline `scientific_report` additionally writes
  `reports/scientific_plan.json` (with `run_id`, `generated_at`) and the full run report.
- Prompts available (`Qwen-Harness/prompts/`): `evidence-extractor.md`,
  `experiment-planner.md`, `feedback-planner.md`, `gap-analyst.md`,
  `generation-architecture.md`, `generation-file.md`,
  `generation-repair-file.md`, `generation-repair.md`, `hypothesis-critic.md`,
  `hypothesis-generator.md`, `problem-framer.md`, `report-writer.md`,
  `result-analyst.md`.
- Skills the harness scans (`<repo>/.qoder/skills`, `CORE_SKILLS`):
  `qwen-harness-orchestration`, `scientific-evidence-hypothesis`,
  `xuhui-route-builder-engineering`, `weather-environment-pipeline`,
  `evaluation-qwen-experiments`, `web-product-integration`. Each directory needs a
  `SKILL.md` with YAML front matter whose `name` equals the directory name and a
  non-empty `description`.
- `SCIENTIFIC_BOUNDARIES` (must appear verbatim in reports/limitations):
  `PM2.5 暴露为网格/站点融合估计，不是站点实测或传感器实测值`,
  `花粉为日级背景/代理指标，不是逐时实测浓度`,
  `噪声为 0-100 风险代理，不是声级计实测`,
  `接驳距离为 GCJ-02 直线估算，实际道路距离通常更长`,
  `预设画像为固定案例矩阵，不解释为独立人群样本，不外推临床或人群结论`.
- `PAPER_TITLE` (deterministic builder): `多目标环境暴露约束与个性化城市健身出行路线选择：基于上海徐汇预设画像矩阵的预注册对照实验`.
- `_materialize_generated_data` runs the **generated**
  `xuhui_route_builder/src/xuhui_route_builder/generate_data.py` as
  `main(data_dir)` and `weather_api_data/src/weather_api_data/web_export.py` as
  `publish_web(source, output_path=...)` (it inspects the signature and passes
  `data_dir` when the parameter is named `data_dir`) to produce the three
  `_DEFERRED_DATA_PATHS` files; both builders must exist and exit `0` within 120 s.

"""恢复规划（设计文档 01 §21）。

实现规则：
1. 读取 ``state.json`` 与阶段输入哈希；
2. 并发恢复由 ``RunStore.acquire_lock`` 拒绝（活进程持锁时）；
3. 最近阶段停留在 ``running`` 且无完整输出时标记 ``retryable``；
4. 已通过阶段的输入哈希未变化时跳过；
5. 配置、Skill、Git HEAD 或模块数据快照变化时记录漂移并继续
   （CLI 非交互，漂移从不静默阻塞恢复）；
6. 网页发布保持原子性（见 ``stages.publish_run_payload``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..logging_utils import get_logger
from ..models import RunContext, WorkflowConfig
from ..paths import HarnessPaths
from ..provenance import config_hashes, git_snapshot, module_data_hashes
from ..run_store import RunStore

LOGGER = get_logger("workflow.resume")


@dataclass
class ResumePlan:
    """恢复计划：从哪里继续、哪些阶段重试、检测到的漂移与说明。"""

    start_index: int
    skipped: list[str] = field(default_factory=list)
    retryable: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _skill_hash(paths: HarnessPaths, name: str) -> str | None:
    try:
        from ..skills import SkillRegistry

        document = SkillRegistry(paths.repo_root).discover().get(name)
    except Exception:  # noqa: BLE001 - 漂移检测不得使恢复崩溃
        return None
    else:
        return document.sha256 if document else None


def _detect_drift(context: RunContext, paths: HarnessPaths) -> list[str]:
    manifest = context.manifest
    drift: list[str] = []

    try:
        git = git_snapshot(paths.repo_root)
        if manifest.git_head and git.head and git.head != manifest.git_head:
            drift.append(f"git_head 变化: {manifest.git_head[:12]} -> {git.head[:12]}")
    except Exception:  # noqa: BLE001 - git 不可用时跳过该项检测
        LOGGER.warning("git 漂移检测失败，已跳过")

    try:
        current_configs = config_hashes(paths.config_dir)
        for rel, digest in manifest.config_hashes.items():
            if current_configs.get(rel) != digest:
                drift.append(f"配置变化: {rel}")
    except Exception:  # noqa: BLE001
        LOGGER.warning("配置漂移检测失败，已跳过")

    for name, digest in manifest.skills_hashes.items():
        current = _skill_hash(paths, name)
        if current is None:
            drift.append(f"技能缺失: {name}")
        elif current != digest:
            drift.append(f"技能变化: {name}")

    try:
        current_data, _missing = module_data_hashes(
            {"route": paths.route_module, "environment": paths.environment_module}
        )
        for rel, digest in manifest.module_data_hashes.items():
            if current_data.get(rel) != digest:
                drift.append(f"模块数据变化: {rel}")
    except Exception:  # noqa: BLE001
        LOGGER.warning("模块数据漂移检测失败，已跳过")
    return drift


def plan_resume(
    run_store: RunStore,
    context: RunContext,
    workflow: WorkflowConfig,
    paths: HarnessPaths,
) -> ResumePlan:
    """依据 ``state.json`` 与阶段哈希规划恢复起点。"""
    state = context.state
    plan = ResumePlan(start_index=0)
    plan.drift = _detect_drift(context, paths)

    stage_names = [stage.name for stage in workflow.stages]
    statuses = state.stage_statuses

    # 规则 3：中断在 running 且无完整输出的阶段 -> 可重试。
    for name in stage_names:
        if statuses.get(name) in {"running", "retryable"}:
            output_path = run_store.stage_output_path(name, "output")
            if not output_path.is_file():
                plan.retryable.append(name)
                plan.notes.append(f"阶段 {name} 上次中断，标记为可重试")

    # 规则 4：逐个确认已通过阶段，输入哈希变化则从该阶段重跑。
    first_unfinished: int | None = None
    for index, name in enumerate(stage_names):
        status = statuses.get(name, "pending")
        if status in {"passed", "skipped"}:
            stored_hash = state.stage_input_hashes.get(name)
            input_path = run_store.stage_output_path(name, "input")
            if stored_hash and input_path.is_file():
                current = run_store.stage_sha256(name, "input")
                if current is not None and current != stored_hash:
                    plan.notes.append(f"阶段 {name} 输入哈希变化，从该阶段重跑")
                    first_unfinished = index
                    break
            plan.skipped.append(name)
            continue
        first_unfinished = index
        break

    plan.start_index = first_unfinished if first_unfinished is not None else len(stage_names)
    if plan.start_index >= len(stage_names):
        plan.notes.append("所有阶段已完成；仅补跑被授权的新操作（如发布）")
        if context.options.publish_web and "publish_web" in stage_names:
            plan.start_index = stage_names.index("publish_web")
    if plan.drift:
        plan.notes.append(f"检测到 {len(plan.drift)} 项漂移，已记录到 state.drift_records")
    return plan

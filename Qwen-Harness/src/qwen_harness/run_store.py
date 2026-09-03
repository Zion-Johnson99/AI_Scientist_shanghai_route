"""Run directory storage with atomic writes (design doc section 7).

Layout: ``runtime/runs/<run-id>/{inputs,sources,skills,stages,modules,
experiments,reports,publish}`` plus ``state.json``, ``run_manifest.json``,
``events.jsonl`` and ``lock.json``. All writes go through
``tmp -> flush -> fsync -> os.replace`` so a crash never leaves a torn file.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import ValidationError

from . import __version__ as HARNESS_VERSION
from .config import HarnessConfig, HarnessSettings
from .errors import InputContractError, PathBoundaryError, RunStateError
from .logging_utils import get_logger
from .models import (
    EvidenceCard,
    ResearchGoal,
    RunContext,
    RunEvent,
    RunManifest,
    RunOptions,
    RunState,
    SourceRecord,
    WorkflowConfig,
)
from .paths import HarnessPaths
from .provenance import config_hashes, git_snapshot, module_data_hashes, sha256_file

LOGGER = get_logger("run_store")

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
RUN_SUBDIRS = (
    "inputs",
    "sources",
    "skills",
    "stages",
    "modules",
    "experiments",
    "reports",
    "publish",
)
_STAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STAGE_KINDS = {"input": "input.json", "output": "output.json", "audit": "audit.json"}

T = TypeVar("T")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_run_id() -> str:
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid.uuid4().hex[:8]}"


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunStore:
    """Bound to one run after create_run()/load_run()."""

    def __init__(
        self, paths: HarnessPaths, settings: HarnessSettings, config: HarnessConfig
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.config = config
        self._run_id: str | None = None
        self._run_dir: Path | None = None

    # -- binding -----------------------------------------------------------
    @property
    def run_id(self) -> str:
        if self._run_id is None:
            raise RunStateError(
                "RunStore 尚未绑定运行", suggested_action="先调用 create_run 或 load_run"
            )
        return self._run_id

    @property
    def run_dir(self) -> Path:
        if self._run_dir is None:
            raise RunStateError(
                "RunStore 尚未绑定运行", suggested_action="先调用 create_run 或 load_run"
            )
        return self._run_dir

    def _resolve(self, relative: str) -> Path:
        candidate = (self.run_dir / relative).resolve()
        try:
            candidate.relative_to(self.run_dir.resolve())
        except ValueError as exc:
            raise PathBoundaryError(
                f"运行目录写入越界: {relative}",
                details={"relative": relative, "resolved": str(candidate)},
            ) from exc
        return candidate

    # -- run lifecycle -------------------------------------------------------
    def create_run(
        self,
        goal: ResearchGoal,
        options: RunOptions,
        workflow: WorkflowConfig | None = None,
        skills_hashes: dict[str, str] | None = None,
    ) -> RunContext:
        run_id = options.run_id or generate_run_id()
        if not RUN_ID_RE.match(run_id):
            raise InputContractError(
                f"非法 run-id: {run_id!r}",
                suggested_action="run-id 仅允许字母数字与 '._-'，长度 3-64",
            )
        run_dir = self.paths.runs_dir / run_id
        if run_dir.exists():
            raise InputContractError(
                f"运行 {run_id} 已存在",
                run_id=run_id,
                suggested_action="使用 qwen-harness resume 继续，或换一个 --run-id",
            )
        run_dir.mkdir(parents=True)
        for sub in RUN_SUBDIRS:
            (run_dir / sub).mkdir(exist_ok=True)
        self._run_id = run_id
        self._run_dir = run_dir

        self.write_json_atomic("inputs/research_goal.json", goal.model_dump(mode="json"))
        self.write_json_atomic("inputs/run_options.json", options.model_dump(mode="json"))

        manifest = self._build_manifest(run_id, options, workflow, skills_hashes or {})
        self.write_json_atomic("run_manifest.json", manifest.model_dump(mode="json"))

        state = RunState(
            run_id=run_id,
            status="running",
            iteration=1,
            max_iterations=options.max_iterations,
            started_at=manifest.created_at,
            updated_at=manifest.created_at,
        )
        self.save_state(state)
        self.emit(
            "run_created",
            f"运行 {run_id} 已创建（workflow={manifest.workflow_name}）",
            details={"workflow": manifest.workflow_name, "offline": manifest.offline},
        )
        return RunContext(
            run_id=run_id,
            run_dir=str(run_dir),
            goal=goal,
            options=options,
            manifest=manifest,
            state=state,
        )

    def _build_manifest(
        self,
        run_id: str,
        options: RunOptions,
        workflow: WorkflowConfig | None,
        skills_hashes: dict[str, str],
    ) -> RunManifest:
        git = git_snapshot(self.paths.repo_root)
        module_roots = {
            "route": self.paths.route_module,
            "environment": self.paths.environment_module,
        }
        data_hashes, missing = module_data_hashes(module_roots)
        if missing:
            LOGGER.warning("模块关键数据缺失（降级运行）: %s", ", ".join(missing[:8]))
        return RunManifest(
            run_id=run_id,
            created_at=_utc_now(),
            repo_root=str(self.paths.repo_root),
            git_branch=git.branch,
            git_head=git.head,
            worktree_clean=git.clean,
            harness_version=HARNESS_VERSION,
            python_version=platform.python_version(),
            platform=platform.platform(),
            model_name=self.config.model.name,
            temperature=self.config.model.temperature,
            seed=self.config.model.seed,
            stage_reasoning_effort=dict(self.config.model.stage_reasoning_effort),
            workflow_name=workflow.name if workflow else options.workflow,
            workflow_version=workflow.version if workflow else "1.0",
            skills_hashes=dict(skills_hashes),
            config_hashes=config_hashes(self.paths.config_dir),
            module_data_hashes=data_hashes,
            network_enabled=options.allow_network and not options.offline,
            module_write_enabled=False,
            publish_enabled=options.publish_web,
            approval_mode=options.approval_mode,
            offline=options.offline,
        )

    def load_run(self, run_id: str) -> RunContext:
        if not RUN_ID_RE.match(run_id or ""):
            raise InputContractError(f"非法 run-id: {run_id!r}")
        run_dir = self.paths.runs_dir / run_id
        if not run_dir.is_dir():
            raise RunStateError(
                f"运行不存在: {run_id}", run_id=run_id, suggested_action="用 list-runs 查看可用运行"
            )
        self._run_id = run_id
        self._run_dir = run_dir

        def _required(relative: str, model: type[T]) -> T:
            data = self.read_json(relative)
            if data is None:
                raise RunStateError(
                    f"运行 {run_id} 缺少 {relative}",
                    run_id=run_id,
                    suggested_action="运行状态已损坏，请新建运行",
                )
            try:
                return model.model_validate(data)  # type: ignore[attr-defined]
            except Exception as exc:  # pydantic ValidationError
                raise RunStateError(
                    f"运行 {run_id} 的 {relative} 不符合契约: {exc}",
                    run_id=run_id,
                    suggested_action="运行状态已损坏，请新建运行",
                ) from exc

        goal = _required("inputs/research_goal.json", ResearchGoal)
        options = _required("inputs/run_options.json", RunOptions)
        manifest = _required("run_manifest.json", RunManifest)
        state = _required("state.json", RunState)
        return RunContext(
            run_id=run_id,
            run_dir=str(run_dir),
            goal=goal,
            options=options,
            manifest=manifest,
            state=state,
        )

    def save_state(self, state: RunState) -> None:
        state.updated_at = _utc_now()
        self.write_json_atomic("state.json", state.model_dump(mode="json"))

    # -- atomic primitives ----------------------------------------------------
    def write_bytes_atomic(self, relative: str, data: bytes) -> Path:
        target = self._resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        return target

    def write_json_atomic(self, relative: str, data: Any) -> Path:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n"
        return self.write_bytes_atomic(relative, text.encode("utf-8"))

    def append_jsonl(self, relative: str, item: Any) -> None:
        target = self._resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def read_json(self, relative: str) -> dict[str, Any] | None:
        path = self._resolve(relative)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunStateError(
                f"运行文件 {relative} 不可读: {exc}",
                run_id=self.run_id,
                suggested_action="运行状态可能已损坏，请新建运行",
            ) from exc

    # -- events ---------------------------------------------------------------
    def emit(
        self,
        event_type: str,
        message: str,
        *,
        stage: str | None = None,
        status: str | None = None,
        details: dict[str, object] | None = None,
        elapsed_ms: float | None = None,
    ) -> RunEvent:
        event = RunEvent(
            ts=_utc_now(),
            run_id=self.run_id,
            stage=stage,
            event_type=event_type,
            status=status,
            message=message,
            details=dict(details or {}),
            elapsed_ms=elapsed_ms,
        )
        self.append_jsonl("events.jsonl", event)
        return event

    # -- stage artifacts ---------------------------------------------------------
    def _check_stage_name(self, stage: str) -> None:
        if not _STAGE_NAME_RE.match(stage or ""):
            raise InputContractError(f"非法阶段名: {stage!r}")

    def stage_output_path(self, stage: str, kind: str = "output") -> Path:
        self._check_stage_name(stage)
        if kind not in _STAGE_KINDS:
            raise InputContractError(f"非法阶段文件类型: {kind!r}")
        return self.run_dir / "stages" / stage / _STAGE_KINDS[kind]

    def _write_stage_file(self, stage: str, kind: str, data: Any) -> Path:
        relative = f"stages/{stage}/{_STAGE_KINDS[kind]}"
        return self.write_json_atomic(relative, data)

    def write_stage_input(self, stage: str, data: Any) -> Path:
        return self._write_stage_file(stage, "input", data)

    def write_stage_output(self, stage: str, data: Any) -> Path:
        return self._write_stage_file(stage, "output", data)

    def write_stage_audit(self, stage: str, data: Any) -> Path:
        return self._write_stage_file(stage, "audit", data)

    def read_stage_output(self, stage: str) -> dict[str, Any] | None:
        path = self.stage_output_path(stage, "output")
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunStateError(
                f"阶段 {stage} 输出不可读: {exc}",
                run_id=self.run_id,
                stage=stage,
                suggested_action="运行状态可能已损坏，考虑新建运行",
            ) from exc

    def stage_sha256(self, stage: str, kind: str = "output") -> str | None:
        path = self.stage_output_path(stage, kind)
        if not path.is_file():
            return None
        return sha256_file(path)

    # -- sources / evidence ------------------------------------------------------
    def append_source_record(self, record: SourceRecord) -> None:
        self.append_jsonl("sources/source_registry.jsonl", record)

    def append_evidence_card(self, card: EvidenceCard) -> None:
        self.append_jsonl("sources/evidence_cards.jsonl", card)

    def _load_jsonl(self, relative: str) -> Iterable[dict[str, Any]]:
        path = self._resolve(relative)
        if not path.is_file():
            return []
        items: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.warning("%s 第 %d 行损坏，已跳过", relative, line_number)
                continue
            if isinstance(data, dict):
                items.append(data)
        return items

    def load_source_registry(self) -> dict[str, SourceRecord]:
        registry: dict[str, SourceRecord] = {}
        for item in self._load_jsonl("sources/source_registry.jsonl"):
            try:
                record = SourceRecord.model_validate(item)
            except ValidationError:  # 损坏条目跳过
                LOGGER.warning("来源记录损坏，已跳过: %s", item.get("source_id", "?"))
                continue
            registry[record.source_id] = record
        return registry

    def load_evidence_cards(self) -> list[EvidenceCard]:
        cards: list[EvidenceCard] = []
        for item in self._load_jsonl("sources/evidence_cards.jsonl"):
            try:
                cards.append(EvidenceCard.model_validate(item))
            except ValidationError:  # 损坏条目跳过
                LOGGER.warning("证据卡损坏，已跳过: %s", item.get("card_id", "?"))
        return cards

    # -- locking -----------------------------------------------------------------
    def acquire_lock(self) -> None:
        lock_path = self.run_dir / "lock.json"
        if lock_path.is_file():
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            pid = int(existing.get("pid") or 0)
            if _is_pid_alive(pid):
                raise RunStateError(
                    f"运行 {self.run_id} 被进程 {pid} 锁定",
                    run_id=self.run_id,
                    suggested_action="等待该进程结束，或确认其已退出后删除 lock.json",
                )
            LOGGER.warning("检测到过期锁（pid=%s 已退出），接管运行 %s", pid, self.run_id)
        payload = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "run_id": self.run_id,
            "acquired_at": _utc_now().isoformat(),
        }
        tmp = lock_path.with_name(f"lock.json.tmp-{uuid.uuid4().hex[:8]}")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, lock_path)

    def release_lock(self) -> None:
        if self._run_dir is None:
            return
        lock_path = self._run_dir / "lock.json"
        if not lock_path.is_file():
            return
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if int(existing.get("pid") or -1) == os.getpid():
            try:
                lock_path.unlink()
            except OSError:  # pragma: no cover - best effort cleanup
                LOGGER.warning("无法删除锁文件: %s", lock_path)

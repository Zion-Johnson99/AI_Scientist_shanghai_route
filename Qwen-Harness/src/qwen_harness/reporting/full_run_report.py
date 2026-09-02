"""生成由引擎审计数据驱动的完整运行报告。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

REPORT_RELATIVE = "reports/full_run_report.md"

_MODULES = (
    ("harness", "Harness 编排", "Qwen-Harness"),
    ("route", "路线构建", "xuhui_route_builder"),
    ("environment", "环境数据", "weather_api_data"),
    ("evaluation", "评价模型", "evaluation_model_qwen"),
)
_SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".tsx", ".html", ".css", ".json", ".yaml", ".yml"}
_IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "runtime",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _single_line(value: object, limit: int = 180) -> str:
    text = " ".join(str(value or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)} min {remainder:.1f} s"


def _source_structure(root: Path) -> tuple[int, str]:
    if not root.is_dir():
        return 0, "目录缺失"
    entries = sorted(
        item.name
        for item in root.iterdir()
        if item.name not in _IGNORED_DIRS and not item.name.startswith(".")
    )
    source_count = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in _IGNORED_DIRS and not name.startswith(".")]
        source_count += sum(Path(name).suffix.lower() in _SOURCE_SUFFIXES for name in files)
    structure = "、".join(entries[:10])
    if len(entries) > 10:
        structure += f"等 {len(entries)} 项"
    return source_count, structure or "根目录暂无可展示条目"


def _stage_rows(context: WorkflowContext) -> tuple[list[str], float]:
    rows: list[str] = []
    audited_seconds = 0.0
    for stage in context.workflow.stages:
        audit = _read_json(context.run_dir / "stages" / stage.name / "audit.json")
        elapsed_ms = audit.get("elapsed_ms")
        elapsed = float(elapsed_ms) / 1000 if isinstance(elapsed_ms, (int, float)) else None
        if elapsed is not None:
            audited_seconds += elapsed
        status = context.state.stage_statuses.get(stage.name, "pending")
        summary = _single_line(audit.get("summary") or "-")
        rows.append(f"| `{stage.name}` | {status} | {_duration(elapsed)} | {summary} |")
    return rows, audited_seconds


def _total_elapsed(context: WorkflowContext) -> float:
    start = context.state.started_at
    end = context.state.finished_at or datetime.now(timezone.utc)
    return max(0.0, (end - start).total_seconds())


def _module_rows(context: WorkflowContext) -> list[str]:
    preflight = context.read_stage_output("module_preflight") or {}
    preflight_statuses = preflight.get("preflight_statuses")
    if not isinstance(preflight_statuses, dict):
        preflight_statuses = {}
    execution = context.read_stage_output("module_execution") or {}
    operations = execution.get("executed_operations")
    if not isinstance(operations, list):
        operations = []

    rows: list[str] = []
    generated_source_root = context.run_dir / "workspace" / "source"
    for key, label, directory in _MODULES:
        root = generated_source_root / directory
        source_count, structure = _source_structure(root)
        matching = [str(item) for item in operations if str(item).startswith(f"{key}:")]
        execution_status = context.state.stage_statuses.get("module_execution", "pending")
        detail = (
            "本轮工作区已生成"
            if key == "harness" and source_count
            else "本轮工作区缺少源码"
            if key == "harness"
            else f"{execution_status}；记录 {len(matching)} 项操作"
        )
        preflight_status = "不适用" if key == "harness" else preflight_statuses.get(key, "pending")
        rows.append(
            f"| {label} | `{directory}` | {preflight_status} | "
            f"{detail} | {source_count} | {_single_line(structure)} |"
        )
    return rows


def _gate_rows(context: WorkflowContext) -> list[str]:
    rows: list[str] = []
    for stage in context.workflow.stages:
        audit = _read_json(context.run_dir / "stages" / stage.name / "audit.json")
        gate = audit.get("gate_result")
        if not isinstance(gate, dict):
            continue
        raw_checks = gate.get("checks")
        checks: list[Any] = raw_checks if isinstance(raw_checks, list) else []
        failed = [
            str(item.get("name"))
            for item in checks
            if isinstance(item, dict) and not item.get("passed")
        ]
        result = "通过" if gate.get("passed") else "未通过"
        detail = f"检查 {len(checks)} 项"
        if failed:
            detail += f"；未通过：{'、'.join(failed)}"
        gate_name = _single_line(gate.get("gate") or stage.name)
        rows.append(f"| `{stage.name}` | {gate_name} | {result} | {detail} |")
    if not rows:
        rows.append("| - | - | 待执行 | 尚无门禁审计数据 |")
    return rows


def _selected_hypothesis(context: WorkflowContext) -> tuple[str, str]:
    selection = context.read_stage_output("hypothesis_selection") or {}
    hypothesis_id = str(selection.get("selected_hypothesis_id") or "待选择")
    generation = context.read_stage_output("hypothesis_generation") or {}
    hypotheses = generation.get("hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict) and item.get("hypothesis_id") == hypothesis_id:
                return hypothesis_id, _single_line(item.get("statement"), 500)
    return hypothesis_id, "尚无可用的假设陈述"


def _web_status(context: WorkflowContext) -> str:
    candidates = (
        context.run_dir / "publish" / "local-product" / "web" / "index.html",
        context.run_dir / "publish" / "web" / "index.html",
    )
    if any(path.is_file() for path in candidates):
        return "已生成本地地图网页"
    if context.state.stage_statuses.get("web_payload") == "passed":
        return "网页数据已生成，本地产品包待整理"
    return "待 web_payload 阶段执行"


def write_full_run_report(context: WorkflowContext) -> Path:
    """写入 reports/full_run_report.md, 执行状态仅取自引擎状态与审计文件。"""
    stage_rows, audited_seconds = _stage_rows(context)
    module_rows = _module_rows(context)
    gate_rows = _gate_rows(context)
    hypothesis_id, hypothesis = _selected_hypothesis(context)
    interpretation = context.read_stage_output("experiment_analysis") or {}
    feedback = context.read_stage_output("feedback_decision") or {}
    final_validation = context.read_stage_output("final_validation") or {}

    status = context.state.status
    support = context.state.final_support_status or interpretation.get("status") or "待判定"
    checks_dir = context.run_dir / "publish" / "checks"
    check_count = (
        sum(1 for path in checks_dir.rglob("*") if path.is_file()) if checks_dir.is_dir() else 0
    )
    artifacts = [
        "reports/full_run_report.md",
        "reports/scientific_plan.json",
        "reports/scientific_plan.md",
        "reports/experiment_report.md",
        "publish/reports/完整运行报告.md",
        "publish/reports/科学计划.md",
        "publish/reports/实验报告.md",
        "publish/local-product/web/index.html",
        "publish/checks/",
    ]
    artifact_lines = []
    for item in artifacts:
        exists = (context.run_dir / item.rstrip("/")).exists()
        artifact_lines.append(f"- `{item}` — {'已生成' if exists else '待生成'}")

    lines = [
        "# Qwen Harness 完整运行报告",
        "",
        "> 执行状态、耗时、门禁和产物路径来自 Harness 引擎审计；模型内容仅用于科研摘要。",
        "",
        "## 运行概览",
        "",
        f"- 运行 ID：`{context.run_id}`",
        f"- 工作流：`{context.workflow.name}`",
        f"- 运行状态：{status}",
        f"- 支持结论：{support}",
        f"- 运行模式：{'offline fixture' if context.options.offline else '千问 API'}",
        f"- 总耗时：{_duration(_total_elapsed(context))}",
        f"- 已审计阶段耗时合计：{_duration(audited_seconds)}",
        f"- 本地网页：{_web_status(context)}",
        f"- checks 文件数：{check_count}",
        "",
        "## 阶段执行",
        "",
        "| 阶段 | 状态 | 耗时 | 主要摘要 |",
        "| --- | --- | ---: | --- |",
        *stage_rows,
        "",
        "## 四个源码模块",
        "",
        "| 模块 | 代码目录 | 预检 | 执行情况 | 源文件数 | 根目录结构 |",
        "| --- | --- | --- | --- | ---: | --- |",
        *module_rows,
        "",
        "## 门禁与检测",
        "",
        "| 阶段 | 门禁 | 结果 | 详情 |",
        "| --- | --- | --- | --- |",
        *gate_rows,
        "",
        f"- 最终验证阶段：{context.state.stage_statuses.get('final_validation', 'pending')}",
        f"- 最终验证输出：{_single_line(final_validation or '待生成', 500)}",
        "",
        "## 假设与实验结论",
        "",
        f"- 选定假设：`{hypothesis_id}` — {hypothesis}",
        f"- 实验支持状态：{support}",
        f"- 科研解读：{_single_line(interpretation.get('interpretation') or '待实验分析', 800)}",
        f"- 迭代决策：{_single_line(feedback.get('reason') or '待反馈决策', 800)}",
        "",
        "## 关键产物路径",
        "",
        *artifact_lines,
        "",
    ]
    return context.store.write_bytes_atomic(REPORT_RELATIVE, "\n".join(lines).encode("utf-8"))

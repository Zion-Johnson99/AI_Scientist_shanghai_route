"""Phase 1: round-1 defect baseline.

Reads ONLY the round-1 diagnostic materials permitted by the round-2 prompt
(run_manifest.json, state.json, events.jsonl, checks/**, commands/*.log,
metrics/quality summaries). It never opens round-1 workspace/source/** or
round-1 publish/local-product/**.

Emits checks/round1_defect_baseline.json and reports/第一轮缺陷基线.md.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parents[1]
R1 = RUN_DIR.parent / "run-20260902T035556Z-0a43adb5"

ALLOWED_READS = [
    "run_manifest.json",
    "state.json",
    "events.jsonl",
    "checks/**",
    "commands/*.log",
    "derived_config.json",
]
FORBIDDEN_READS = [
    "workspace/source/**",
    "publish/local-product/**",
    "round-1 generated web pages, CSS, JS, GeoJSON payloads",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def collect_checks(node: Any, origin: str, out: list[dict[str, Any]]) -> None:
    """Flatten any nested {name,status/passed} entries into a check list."""
    if isinstance(node, dict):
        name = node.get("name") or node.get("check") or node.get("id")
        status = node.get("status")
        passed = node.get("passed")
        if isinstance(name, str) and (status is not None or passed is not None):
            out.append(
                {
                    "origin": origin,
                    "name": name,
                    "status": status,
                    "passed": bool(passed) if passed is not None else status == "passed",
                    "required": bool(node.get("required", False)),
                    "category": node.get("category"),
                    "exit_code": node.get("exit_code"),
                    "error": node.get("error"),
                }
            )
        for value in node.values():
            collect_checks(value, origin, out)
    elif isinstance(node, list):
        for value in node:
            collect_checks(value, origin, out)


def scan_command_logs() -> dict[str, Any]:
    log_dir = R1 / "commands"
    summary: dict[str, Any] = {"log_files": 0, "keyword_hits": Counter()}
    keywords = {
        "pytest_failure": re.compile(r"^(FAILED|ERROR)\s", re.M),
        "ruff_error": re.compile(r"Found \d+ error", re.I),
        "pyright_error": re.compile(r"\d+ errors?, \d+ warnings?", re.I),
        "node_failure": re.compile(r"# fail \d+|not ok \d+", re.I),
        "traceback": re.compile(r"Traceback \(most recent call last\)"),
        "import_error": re.compile(r"ModuleNotFoundError|ImportError"),
    }
    if not log_dir.exists():
        return summary
    for path in sorted(log_dir.rglob("*.log")):
        summary["log_files"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, pattern in keywords.items():
            hits = len(pattern.findall(text))
            if hits:
                summary["keyword_hits"][key] += hits
    summary["keyword_hits"] = dict(summary["keyword_hits"])
    return summary


def main() -> int:
    checks: list[dict[str, Any]] = []
    for path in sorted((R1 / "checks").rglob("*.json")):
        payload = load_json(path)
        if payload is not None:
            collect_checks(payload, f"checks/{path.relative_to(R1 / 'checks').as_posix()}", checks)

    gq = load_json(R1 / "checks" / "generated_quality.json") or {}
    state = load_json(R1 / "state.json") or {}
    smoke = load_json(R1 / "checks" / "browser_smoke_final.json") or {}
    manifest = load_json(R1 / "run_manifest.json") or {}
    log_scan = scan_command_logs()

    gq_checks = [c for c in checks if c["origin"].startswith("checks/generated_quality.json")]
    required_failed = sorted(
        {c["name"] for c in gq_checks if c["required"] and not c["passed"]}
    )
    all_failed = sorted({c["name"] for c in gq_checks if not c["passed"]})
    all_passed = sorted({c["name"] for c in gq_checks if c["passed"]})

    stage_statuses: dict[str, str] = state.get("stage_statuses", {}) or {}
    stages_passed = [k for k, v in stage_statuses.items() if v == "passed"]
    stages_not_passed = {k: v for k, v in stage_statuses.items() if v != "passed"}

    smoke_checks = smoke.get("checks", {}) or {}
    smoke_flags = {
        "top_level_passed": smoke.get("passed"),
        "recommendation_api": smoke.get("recommendation_api"),
        "launcher_mode": smoke.get("launcher_mode"),
        "route_items": smoke_checks.get("route_items"),
        "route_layers": smoke_checks.get("route_layers"),
        "loaded_map_tiles": smoke_checks.get("loaded_map_tiles"),
        "console_errors": smoke_checks.get("console_errors"),
        "selected_route_id": smoke_checks.get("selected_route_id"),
        "environment_detail_visible": smoke_checks.get("environment_detail_visible"),
        "note": smoke.get("note"),
    }

    arch_dir = R1 / "checks" / "browser-architecture-smoke"
    arch_files = (
        sorted(p.name for p in arch_dir.rglob("*") if p.is_file()) if arch_dir.exists() else []
    )

    spatial_gate_files = sorted(
        p.name
        for p in (R1 / "checks").rglob("*.json")
        if re.search(r"route_spatial|spatial_quality|in_district|road_snap|geometry", p.name, re.I)
    )

    defects = [
        {
            "id": "D1",
            "area": "generated_quality",
            "statement": "第一轮 checks/generated_quality.json 整体 passed=false，required 检查未全部通过。",
            "evidence": {
                "generated_quality.passed": gq.get("passed"),
                "required_failed_checks": required_failed,
                "required_failed_count": len(required_failed),
                "total_failed_checks": len(all_failed),
                "total_passed_checks": len(all_passed),
            },
            "severity": "blocker",
            "round2_target": "checks/generated_quality.json 中全部 required 检查通过，passed=true。",
        },
        {
            "id": "D2",
            "area": "test_toolchain",
            "statement": (
                "第一轮 pytest（Qwen-Harness 与 evaluation_model_qwen）、Ruff、Pyright、"
                "Node 契约测试与评价 API 检查存在失败项；命令日志中出现测试失败、"
                "traceback 与导入错误特征。"
            ),
            "evidence": {
                "generated_quality_failed_checks": all_failed,
                "command_log_files_scanned": log_scan["log_files"],
                "command_log_keyword_hits": log_scan["keyword_hits"],
            },
            "severity": "blocker",
            "round2_target": "pytest / Ruff / Pyright / Node 契约测试 / 评价 API 健康检查全部通过。",
        },
        {
            "id": "D3",
            "area": "browser_acceptance",
            "statement": (
                "第一轮浏览器验收只在降级模式下通过：顶层 passed=true，但 "
                "recommendation_api=failed_import_contract、launcher_mode=web_only_degraded，"
                "推荐链路未被真实验收。"
            ),
            "evidence": smoke_flags,
            "severity": "blocker",
            "round2_target": (
                "本地启动脚本 + 评价 API 正常模式下完成桌面与 500x700 移动端验收，"
                "推荐、筛选、详情、地图联动、位置输入、备选路线、错误状态逐项可验证。"
            ),
        },
        {
            "id": "D4",
            "area": "route_card_architecture",
            "statement": (
                "第一轮页面缺少可验收的 route-card 交互架构：浏览器验收只统计了 "
                "route_items / route_layers 数量与单一 selected_route_id，没有对卡片、"
                "详情面板、双向联动、高亮弱化和备选路线做结构化断言。"
            ),
            "evidence": {
                "browser_architecture_smoke_files": arch_files,
                "smoke_asserted_fields": sorted(smoke_checks),
                "missing_card_assertions": [
                    "card_has_detail_button",
                    "card_shows_distance_duration_risk_reason",
                    "primary_plus_two_alternatives",
                    "list_to_map_and_map_to_list_linkage",
                    "selected_highlight_others_dimmed",
                    "access_navigation_entry",
                    "loading_empty_partial_error_states",
                ],
            },
            "severity": "major",
            "round2_target": "12 项可见产品矩阵中至少 8 项通过，且卡片交互逐项有断言与截图。",
        },
        {
            "id": "D5",
            "area": "spatial_quality",
            "statement": (
                "第一轮没有独立的路线空间质量门禁：checks 目录下不存在 "
                "route_spatial_quality / 区内比例 / 道路贴合 / 几何质量检查文件，"
                "徐汇边界、区内轨迹比例、道路贴合与几何拓扑均未被量化验收。"
            ),
            "evidence": {
                "spatial_gate_files_found": spatial_gate_files,
                "spatial_gate_files_count": len(spatial_gate_files),
                "conclusion": "absent_gate",
            },
            "severity": "blocker",
            "round2_target": (
                "90 条路线满足区内比例、道路贴合、距离误差、闭环拓扑、重复边、自交、"
                "折返与端点偏移门槛，90 accepted / 0 needs_review，并逐条地图目检。"
            ),
        },
        {
            "id": "D6",
            "area": "stage_vs_quality_divergence",
            "statement": (
                "第一轮 state.json 记录 status=passed 且全部阶段 passed，"
                "与 generated_quality.json 的 passed=false 直接冲突，"
                "说明阶段完成状态被当成了质量通过状态。"
            ),
            "evidence": {
                "state.status": state.get("status"),
                "state.current_stage": state.get("current_stage"),
                "stages_total": len(stage_statuses),
                "stages_passed": len(stages_passed),
                "stages_not_passed": stages_not_passed,
                "generated_quality.passed": gq.get("passed"),
                "divergence": bool(state.get("status") == "passed" and gq.get("passed") is False),
            },
            "severity": "blocker",
            "round2_target": (
                "最终状态严格区分 passed / failed_quality_gate / "
                "implementation_complete_unverified，禁止把流程结束记录为质量通过。"
            ),
        },
    ]

    baseline: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact": "round1_defect_baseline",
        "round": 2,
        "run_id": RUN_DIR.name,
        "generated_at": utc_now(),
        "round1_run_id": R1.name,
        "read_scope": {
            "allowed_materials_read": ALLOWED_READS,
            "forbidden_materials_not_read": FORBIDDEN_READS,
            "boundary_respected": True,
        },
        "round1_run_manifest_provider": manifest.get("provider") or manifest.get("model") or "unknown",
        "round1_quality_summary": {
            "generated_quality_passed": gq.get("passed"),
            "checks_flattened_total": len(checks),
            "generated_quality_checks_total": len(gq_checks),
            "required_failed": required_failed,
            "failed": all_failed,
            "passed": all_passed,
        },
        "round1_stage_summary": {
            "status": state.get("status"),
            "current_stage": state.get("current_stage"),
            "iteration": state.get("iteration"),
            "max_iterations": state.get("max_iterations"),
            "stage_statuses": stage_statuses,
        },
        "round1_browser_summary": smoke_flags,
        "round1_command_log_scan": log_scan,
        "defects": defects,
        "defect_counts_by_severity": dict(Counter(d["severity"] for d in defects)),
        "evidence_provenance": {
            "raw_data": [
                "run-20260902T035556Z-0a43adb5/checks/generated_quality.json",
                "run-20260902T035556Z-0a43adb5/state.json",
                "run-20260902T035556Z-0a43adb5/checks/browser_smoke_final.json",
                "run-20260902T035556Z-0a43adb5/commands/*.log",
            ],
            "deterministic_computation": [
                "flattened check pass/fail counts",
                "required-failed set",
                "command-log keyword hit counts",
                "stage-vs-quality divergence boolean",
            ],
            "qoder_judgement": [
                "severity assignment (blocker/major)",
                "round2_target wording",
                "interpretation of absent spatial gate as a defect rather than a pass",
            ],
            "manual_setting": [
                "12-item visible product matrix target of >=8 passes (from the round-2 prompt)",
                "90-route portfolio composition (from the round-2 prompt)",
            ],
        },
    }

    out_json = RUN_DIR / "checks" / "round1_defect_baseline.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 第一轮缺陷基线",
        "",
        f"- 第二轮 run：`{RUN_DIR.name}`",
        f"- 第一轮 run：`{R1.name}`",
        f"- 生成时间：{utc_now()}",
        "",
        "## 读取范围",
        "",
        "只读取第一轮允许的诊断材料：",
        "",
    ]
    lines += [f"- `{item}`" for item in ALLOWED_READS]
    lines += ["", "以下内容全程未读取：", ""]
    lines += [f"- {item}" for item in FORBIDDEN_READS]
    lines += [
        "",
        "## 缺陷清单",
        "",
        "| 编号 | 领域 | 严重度 | 结论 |",
        "| --- | --- | --- | --- |",
    ]
    for d in defects:
        lines.append(f"| {d['id']} | {d['area']} | {d['severity']} | {d['statement']} |")
    lines += ["", "## 逐项证据", ""]
    for d in defects:
        lines += [
            f"### {d['id']} {d['area']}",
            "",
            d["statement"],
            "",
            "```json",
            json.dumps(d["evidence"], ensure_ascii=False, indent=2),
            "```",
            "",
            f"第二轮目标：{d['round2_target']}",
            "",
        ]
    lines += [
        "## 证据来源分类",
        "",
        "- 原始数据：第一轮 checks 与 commands 目录中的诊断文件与日志。",
        "- 确定性计算：检查项展平后的通过/失败计数、required 失败集合、日志关键字命中数、阶段状态与质量状态的冲突布尔值。",
        "- Qoder 判断：严重度分级、第二轮目标措辞、把“缺少空间门禁”判定为缺陷而非通过。",
        "- 人工设置：12 项可见产品矩阵至少通过 8 项、90 条路线组合口径，均来自第二轮任务提示词。",
        "",
        "## 关键差异",
        "",
        f"第一轮 `state.json` 的 status 为 `{state.get('status')}`，"
        f"{len(stages_passed)}/{len(stage_statuses)} 个阶段标记为 passed；"
        f"同一 run 的 `checks/generated_quality.json` 中 passed 为 `{gq.get('passed')}`，"
        f"required 失败 {len(required_failed)} 项。"
        "第二轮不得把阶段完成状态直接当作质量通过状态。",
        "",
    ]
    (RUN_DIR / "reports" / "第一轮缺陷基线.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"defects={len(defects)}")
    print(f"gq_passed={gq.get('passed')} required_failed={len(required_failed)} failed={len(all_failed)}")
    print(f"state_status={state.get('status')} stages_passed={len(stages_passed)}/{len(stage_statuses)}")
    print(f"required_failed_names={required_failed}")
    print(f"spatial_gate_files={spatial_gate_files}")
    print(f"log_files={log_scan['log_files']} keyword_hits={log_scan['keyword_hits']}")
    print(f"arch_files={arch_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

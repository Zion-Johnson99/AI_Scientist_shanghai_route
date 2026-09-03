"""EnvironmentDataAdapter：weather_api_data 模块接入（设计文档 01 §15.3）。

只读契约数据：``xuhui_route_builder/data/web/environment_dashboard.json``
与 ``weather_api_data/runtime/exports/`` 下的刷新快照。结构校验覆盖顶层
``metadata/current/forecast/routes``、90 条路线环境记录的 ID 一致性、
时间字段可解析、``status`` 枚举（ok/partial/stale/no_data/error，其中
partial/stale/estimated 语义会以警告形式显式记录）与单位字段。

命令模板（仅在非离线且获得相应授权时执行）：

- 预检/校验：``weather-api-data config-check``、``dry-run``。
- 刷新：``weather-api-data scheduled-refresh --tier <tier>``，仅当
  CLI 显式提供 ``--refresh-environment`` 时允许。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..errors import InputContractError, ModuleCommandError
from .base import ModuleAdapter

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..models import ModuleOperation
    from ..workflow.engine import WorkflowContext

DASHBOARD_RELATIVE = "data/web/environment_dashboard.json"
EXPORT_RELATIVES = (
    "runtime/exports/environment_latest.json",
    "runtime/exports/environment_hourly.json",
    "runtime/exports/grid_environment_latest.json",
    "runtime/exports/pollen_grid_scores.json",
    "runtime/exports/noise_segments.json",
    "runtime/exports/route_environment.json",
)

EXPECTED_ROUTE_COUNT = 90
STATUS_ENUM = frozenset({"ok", "partial", "stale", "no_data", "error"})
REFRESH_TIERS = frozenset({"weather", "hourly", "daily"})
#: 文档化的单位期望；不一致时记录警告而不是直接判错（单位口径以模块为准）。
EXPECTED_UNITS = {"pm2_5": "µg/m³", "noise": "0-100 risk index", "pollen": "0-100 risk index"}


class EnvironmentDataAdapter(ModuleAdapter):
    """环境数据模块 Adapter：离线只读快照，刷新需显式授权。"""

    module = "environment"
    supported_operations = ("environment.read_snapshot", "environment.refresh")

    # -- 预检与快照 -------------------------------------------------------------
    def preflight(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        try:
            errors, structure_warnings = self._check_dashboard(context)
        except InputContractError as exc:
            return self.result("error", errors=[exc.message])
        warnings.extend(structure_warnings)

        paths = self.project_paths(context)
        missing_exports = []
        for relative in EXPORT_RELATIVES:
            path = paths.resolve_path(paths.environment_module / relative, relative)
            if self.optional_project_file(path) is None:
                missing_exports.append(relative)
        if missing_exports:
            warnings.append("环境导出快照缺失（首次刷新前属正常）: " + ", ".join(missing_exports))
        if errors:
            return self.result("error", errors=errors, warnings=warnings)
        if warnings:
            return self.result("partial", warnings=warnings)
        return self.result("ok")

    def snapshot(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        paths = []
        project_paths = self.project_paths(context)
        dashboard = self.optional_project_file(project_paths.environment_dashboard_path)
        if dashboard is not None:
            paths.append(dashboard)
        for relative in EXPORT_RELATIVES:
            candidate = project_paths.resolve_path(
                project_paths.environment_module / relative, relative
            )
            path = self.optional_project_file(candidate)
            if path is None:
                warnings.append(f"快照缺少导出文件: {relative}")
                continue
            paths.append(path)
        if dashboard is None:
            return self.result(
                "error",
                errors=[f"环境仪表盘缺失: {DASHBOARD_RELATIVE}"],
                warnings=warnings,
            )
        hashes = self.hash_files(paths)
        status = "ok" if not warnings else "partial"
        return self.result(
            status,
            input_artifacts=[self.repo_relative(context, path) for path in paths],
            data_hashes=hashes,
            warnings=warnings,
        )

    def validate(self, context: "WorkflowContext") -> Any:
        """模块命令校验：config-check + dry-run；离线/未授权时返回跳过。"""
        if not self.commands_allowed(context):
            return self.skipped(
                "离线模式未执行环境模块命令；read_snapshot 仅读取现有快照文件",
            )
        audits = []
        paths = self.project_paths(context)
        for subcommand in ("config-check", "dry-run"):
            try:
                audits.append(
                    self.run_fixed_command(
                        context,
                        command_id=f"environment.{subcommand.replace('-', '_')}",
                        argv=[
                            "uv",
                            "run",
                            "--directory",
                            str(paths.environment_module),
                            "--frozen",
                            "weather-api-data",
                            subcommand,
                        ],
                        cwd=paths.environment_module,
                    )
                )
            except ModuleCommandError as exc:
                return self.result(
                    "error",
                    commands=audits,
                    errors=[f"环境模块命令 {subcommand} 失败: {exc.message}"],
                )
        return self.result("ok", commands=audits)

    # -- 操作执行 ---------------------------------------------------------------
    def execute(self, operation: "ModuleOperation", context: "WorkflowContext") -> Any:
        op = operation.operation_id
        if op == "environment.read_snapshot":
            return self._read_snapshot(context)
        if op == "environment.refresh":
            return self._refresh(operation, context)
        return self.unknown_operation(operation)

    def _read_snapshot(self, context: "WorkflowContext") -> Any:
        """只读取仓库现有数据文件完成快照读取，离线可用。"""
        try:
            errors, warnings = self._check_dashboard(context)
        except InputContractError as exc:
            return self.result("error", errors=[exc.message])
        if errors:
            return self.result("error", errors=errors, warnings=warnings)
        snapshot = self.snapshot(context)
        merged_warnings = [*snapshot.warnings, *warnings]
        status = "partial" if (merged_warnings or snapshot.status == "partial") else "ok"
        return snapshot.model_copy(update={"status": status, "warnings": merged_warnings})

    def _refresh(self, operation: "ModuleOperation", context: "WorkflowContext") -> Any:
        tier = str(operation.parameters.get("tier", "")).strip()
        if context.options.offline:
            return self.skipped("离线模式禁止刷新环境数据")
        if context.options.refresh_environment == "none":
            return self.skipped("未提供 --refresh-environment 显式授权，使用 last-known-good 快照")
        tier = tier or context.options.refresh_environment
        if tier not in REFRESH_TIERS:
            return self.result(
                "error", errors=[f"非法刷新层级: {tier!r}（允许: weather/hourly/daily）"]
            )
        audit = self.run_fixed_command(
            context,
            command_id="environment.refresh",
            argv=[
                "uv",
                "run",
                "--directory",
                str(self.project_paths(context).environment_module),
                "--frozen",
                "weather-api-data",
                "scheduled-refresh",
                "--tier",
                tier,
            ],
            cwd=self.project_paths(context).environment_module,
            timeout_seconds=1800,
        )
        return self.result("ok", commands=[audit], warnings=[f"已按 {tier} 层级刷新环境数据"])

    # -- 结构校验 ---------------------------------------------------------------
    def _check_dashboard(self, context: "WorkflowContext") -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        dashboard_path = self.project_file(
            self.project_paths(context).environment_dashboard_path, "环境仪表盘"
        )
        dashboard = self.read_json(dashboard_path, "环境仪表盘")
        if not isinstance(dashboard, dict):
            return ["环境仪表盘顶层必须是对象"], warnings

        for key in ("metadata", "current", "forecast", "routes"):
            if not isinstance(dashboard.get(key), dict):
                errors.append(f"环境仪表盘缺少顶层段 {key}")
        if errors:
            return errors, warnings

        metadata = dashboard["metadata"]
        generated_at = metadata.get("generated_at")
        if not isinstance(generated_at, str) or _parse_timestamp(generated_at) is None:
            errors.append("metadata.generated_at 缺失或不是可解析的时间戳")
        metadata_status = metadata.get("status")
        if metadata_status not in STATUS_ENUM:
            errors.append(f"metadata.status 非法: {metadata_status!r}")
        elif metadata_status != "ok":
            stale_reason = metadata.get("stale_reason")
            detail = f"（{stale_reason}）" if isinstance(stale_reason, str) and stale_reason else ""
            warnings.append(f"环境数据整体状态为 {metadata_status}{detail}：评分可靠性会按权重收缩")

        for section in ("current", "forecast"):
            status = dashboard[section].get("status")
            if status not in STATUS_ENUM:
                errors.append(f"{section}.status 非法: {status!r}")

        routes = dashboard["routes"]
        routes_status = routes.get("status", metadata_status)
        if routes_status not in STATUS_ENUM:
            errors.append(f"routes.status 非法: {routes_status!r}")
        items = routes.get("items")
        if not isinstance(items, list):
            errors.append("routes.items 必须是数组")
            return errors, warnings
        declared_count = routes.get("count")
        if declared_count != len(items):
            errors.append(f"routes.count={declared_count!r} 与 items 数量 {len(items)} 不一致")
        if len(items) != EXPECTED_ROUTE_COUNT:
            errors.append(f"路线环境记录应为 {EXPECTED_ROUTE_COUNT} 条，实际 {len(items)}")

        seen_ids: set[str] = set()
        status_counts: dict[str, int] = {}
        estimated_count = 0
        for index, item in enumerate(items):
            where = f"routes.items[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where} 必须是对象")
                continue
            route_id = item.get("route_id")
            if not isinstance(route_id, str) or not route_id:
                errors.append(f"{where}.route_id 缺失")
                continue
            if route_id in seen_ids:
                errors.append(f"{where}.route_id 重复: {route_id}")
            seen_ids.add(route_id)
            status = item.get("status") or self._infer_item_status(item)
            if status not in STATUS_ENUM:
                errors.append(f"{where}.status 非法: {status!r}")
            else:
                status_counts[status] = status_counts.get(status, 0) + 1
            estimated_count += self._check_metrics(item, where, errors, warnings)

        if status_counts.get("partial", 0):
            warnings.append(
                f"{status_counts['partial']} 条路线环境状态为 partial（部分来源缺失，评分按可靠性收缩）"
            )
        if status_counts.get("stale", 0):
            warnings.append(
                f"{status_counts['stale']} 条路线环境状态为 stale（超过有效期，评分按中性分计入）"
            )
        if estimated_count:
            warnings.append(f"{estimated_count} 个指标块为 estimated 估算值（非站点实测）")

        self._cross_check_route_ids(context, seen_ids, errors, warnings)
        return errors, warnings

    def _check_metrics(
        self, item: dict[str, Any], where: str, errors: list[str], warnings: list[str]
    ) -> int:
        estimated_count = 0
        pm25 = item.get("pm2_5")
        noise = item.get("noise")
        pollen_daily = item.get("pollen_daily")
        if not isinstance(pm25, dict):
            errors.append(f"{where}.pm2_5 缺失")
        else:
            estimated_count += self._check_metric(pm25, f"{where}.pm2_5", "pm2_5", errors, warnings)
        if not isinstance(noise, dict):
            errors.append(f"{where}.noise 缺失")
        else:
            estimated_count += self._check_metric(
                noise, f"{where}.noise", "noise", errors, warnings
            )
        if isinstance(pollen_daily, dict):
            estimated_count += self._check_metric(
                pollen_daily, f"{where}.pollen_daily", "pollen", errors, warnings
            )
        elif not isinstance(pollen_daily, list):
            errors.append(f"{where}.pollen_daily 需为指标对象或按日数组")
        else:
            for day_index, day in enumerate(pollen_daily):
                if not isinstance(day, dict):
                    errors.append(f"{where}.pollen_daily[{day_index}] 必须是对象")
                    continue
                estimated_count += self._check_metric(
                    day, f"{where}.pollen_daily[{day_index}]", "pollen", errors, warnings
                )
        return estimated_count

    @staticmethod
    def _infer_item_status(item: dict[str, Any]) -> str | None:
        statuses: list[str] = []
        for key in ("pm2_5", "noise"):
            metric = item.get(key)
            if isinstance(metric, dict) and isinstance(metric.get("status"), str):
                statuses.append(metric["status"])
        pollen = item.get("pollen_daily")
        pollen_items = (
            [pollen] if isinstance(pollen, dict) else pollen if isinstance(pollen, list) else []
        )
        statuses.extend(
            day["status"]
            for day in pollen_items
            if isinstance(day, dict) and isinstance(day.get("status"), str)
        )
        for status in ("error", "no_data", "stale", "partial", "ok"):
            if status in statuses:
                return status
        return None

    def _check_metric(
        self,
        metric: dict[str, Any],
        where: str,
        kind: str,
        errors: list[str],
        warnings: list[str],
    ) -> int:
        status = metric.get("status")
        if status not in STATUS_ENUM:
            errors.append(f"{where}.status 非法: {status!r}")
        if metric.get("estimated") not in (True, False):
            errors.append(f"{where}.estimated 必须是布尔值")
        unit = metric.get("unit")
        if not isinstance(unit, str) or not unit:
            errors.append(f"{where}.unit 缺失")
        elif kind in EXPECTED_UNITS and unit != EXPECTED_UNITS[kind]:
            warnings.append(f"{where}.unit={unit!r} 与文档化单位 {EXPECTED_UNITS[kind]!r} 不一致")
        business_time = metric.get("business_time")
        if isinstance(business_time, str) and business_time not in {"static_scenario"}:
            if _parse_timestamp(business_time) is None and len(business_time) != 10:
                errors.append(f"{where}.business_time 无法解析: {business_time!r}")
        return 1 if metric.get("estimated") is True else 0

    def _cross_check_route_ids(
        self,
        context: "WorkflowContext",
        environment_ids: set[str],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        from .route_builder import CATALOG_RELATIVE

        project_paths = self.project_paths(context)
        catalog_candidate = project_paths.resolve_path(
            project_paths.route_module / CATALOG_RELATIVE, "路线目录"
        )
        catalog_path = self.optional_project_file(catalog_candidate)
        if catalog_path is None:
            warnings.append("路线目录缺失，跳过环境-路线 ID 一致性核对")
            return
        try:
            catalog = self.read_json(catalog_path, "路线目录")
        except InputContractError as exc:
            warnings.append(f"路线目录不可读，跳过一致性核对: {exc.message}")
            return
        if not isinstance(catalog, list):
            warnings.append("路线目录顶层不是数组，跳过一致性核对")
            return
        catalog_ids = {
            route_id
            for item in catalog
            if isinstance(item, dict)
            for route_id in (item.get("route_id"),)
            if isinstance(route_id, str) and route_id
        }
        missing = sorted(catalog_ids - environment_ids)
        unexpected = sorted(environment_ids - catalog_ids)
        if missing:
            errors.append(
                f"环境数据缺少路线: {', '.join(missing[:10])}{'…' if len(missing) > 10 else ''}"
            )
        if unexpected:
            errors.append(
                f"环境数据含目录外路线: {', '.join(unexpected[:10])}{'…' if len(unexpected) > 10 else ''}"
            )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

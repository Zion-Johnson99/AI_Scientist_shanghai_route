"""RouteBuilderAdapter：xuhui_route_builder 模块接入（设计文档 01 §15.2）。

只读契约数据：``xuhui_route_builder/data/web/route_catalog.json`` 与
``xuhui_routes.geojson``（及入口、POI、接驳样例等附属文件）。验收口径：
路线总数 90，``walk``/``run``/``bike`` 各 30，目录与 GeoJSON 的
``route_id`` 一致且无重复。科研运行默认不生成路线：
``export-candidates`` / ``generate-routes`` 在 v1 一律返回跳过。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from .base import ModuleAdapter

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..models import ModuleOperation
    from ..workflow.engine import WorkflowContext

EXPECTED_ROUTE_COUNT = 90
EXPECTED_PER_MODE = 30
MODES = ("walk", "run", "bike")

CATALOG_RELATIVE = "data/web/route_catalog.json"
GEOMETRY_RELATIVE = "data/web/xuhui_routes.geojson"
ENTRIES_RELATIVE = "data/web/xuhui_entries.geojson"
POI_RELATIVE = "data/web/poi_catalog.json"
ACCESS_RELATIVE = "data/web/access_cases.json"
OPTIONAL_FILES = (ENTRIES_RELATIVE, POI_RELATIVE, ACCESS_RELATIVE)

#: 操作 ID -> 固定命令末段子命令（命令模板冻结，见设计文档 §15.2）。
_COMMAND_TEMPLATES: dict[str, str] = {
    "route.validate_seeds": "validate-seeds",
    "route.validate_routes": "validate-routes",
}
_DISABLED_V1 = ("route.export_candidates", "route.generate")


class RouteBuilderAdapter(ModuleAdapter):
    """路线模块 Adapter：预检/快照/验收只读文件，命令仅限固定验证类。"""

    module = "route"
    supported_operations = ("route.read_snapshot", "route.validate_seeds", "route.validate_routes")

    # -- 预检与验收 -------------------------------------------------------------
    def preflight(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        try:
            errors, consistency_warnings = self._consistency(context)
        except InputContractError as exc:
            return self.result("error", errors=[exc.message])
        warnings.extend(consistency_warnings)
        paths = self.project_paths(context)
        for relative in OPTIONAL_FILES:
            path = paths.resolve_path(paths.route_module / relative, relative)
            if self.optional_project_file(path) is None:
                warnings.append(f"附属数据文件缺失: {relative}")
        if errors:
            return self.result("error", errors=errors, warnings=warnings)
        if warnings:
            return self.result("partial", warnings=warnings)
        return self.result("ok")

    def snapshot(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        paths = []
        project_paths = self.project_paths(context)
        for relative in (CATALOG_RELATIVE, GEOMETRY_RELATIVE, *OPTIONAL_FILES):
            candidate = project_paths.resolve_path(project_paths.route_module / relative, relative)
            path = self.optional_project_file(candidate)
            if path is None:
                warnings.append(f"快照缺少文件: {relative}")
                continue
            paths.append(path)
        hashes = self.hash_files(paths)
        if CATALOG_RELATIVE.split("/")[-1] not in hashes or GEOMETRY_RELATIVE.split("/")[-1] not in hashes:
            return self.result(
                "error",
                data_hashes=hashes,
                errors=["核心路线产物缺失（route_catalog.json / xuhui_routes.geojson）"],
                warnings=warnings,
            )
        status = "ok" if not warnings else "partial"
        return self.result(
            status,
            input_artifacts=[self.repo_relative(context, path) for path in paths],
            data_hashes=hashes,
            warnings=warnings,
        )

    def validate(self, context: "WorkflowContext") -> Any:
        """验收一致性：90 条、每模式 30、目录与 GeoJSON ID 一致、无重复。"""
        try:
            errors, warnings = self._consistency(context)
        except InputContractError as exc:
            return self.result("error", errors=[exc.message])
        if errors:
            return self.result("error", errors=errors, warnings=warnings)
        status = "partial" if warnings else "ok"
        return self.result(status, warnings=warnings)

    # -- 操作执行 ---------------------------------------------------------------
    def execute(self, operation: "ModuleOperation", context: "WorkflowContext") -> Any:
        op = operation.operation_id
        if op == "route.read_snapshot":
            return self.snapshot(context)
        if op in _DISABLED_V1:
            return self.skipped(
                f"操作 {op} 在 v1 中禁用：科研运行默认不生成/导出路线",
            )
        if op in _COMMAND_TEMPLATES:
            if not self.commands_allowed(context):
                return self.skipped(
                    f"离线模式未执行模块命令 {op}（需要在线授权后重跑）",
                )
            audit = self.run_fixed_command(
                context,
                command_id=op,
                argv=[
                    "uv",
                    "run",
                    "--directory",
                    str(self.project_paths(context).route_module),
                    "--frozen",
                    "xuhui-route-builder",
                    _COMMAND_TEMPLATES[op],
                ],
                cwd=self.project_paths(context).route_module,
            )
            return self.result("ok", commands=[audit])
        return self.unknown_operation(operation)

    # -- 验收细节 ---------------------------------------------------------------
    def _consistency(self, context: "WorkflowContext") -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []

        project_paths = self.project_paths(context)
        catalog_path = self.project_file(
            project_paths.resolve_path(
                project_paths.route_module / CATALOG_RELATIVE, "路线目录"
            ),
            "路线目录",
        )
        catalog = self.read_json(catalog_path, "路线目录")
        if not isinstance(catalog, list):
            return [f"{CATALOG_RELATIVE} 顶层必须是路线数组"], warnings

        mode_counts = {mode: 0 for mode in MODES}
        catalog_ids: list[str] = []
        for index, item in enumerate(catalog):
            where = f"route_catalog[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where} 必须是对象")
                continue
            route_id = item.get("route_id")
            if not isinstance(route_id, str) or not route_id:
                errors.append(f"{where}.route_id 缺失或不是字符串")
                continue
            catalog_ids.append(route_id)
            mode = item.get("route_mode")
            if mode in mode_counts:
                mode_counts[mode] += 1
            else:
                errors.append(f"{where}.route_mode 非法: {mode!r}")
            for field in ("route_name", "validation_status", "geometry_status"):
                if not item.get(field):
                    errors.append(f"{where}.{field} 缺失")

        if len(catalog) != EXPECTED_ROUTE_COUNT:
            errors.append(f"路线数应为 {EXPECTED_ROUTE_COUNT}，实际 {len(catalog)}")
        for mode in MODES:
            if mode_counts[mode] != EXPECTED_PER_MODE:
                errors.append(f"模式 {mode} 应为 {EXPECTED_PER_MODE} 条，实际 {mode_counts[mode]}")
        duplicated = {route_id for route_id in catalog_ids if catalog_ids.count(route_id) > 1}
        if duplicated:
            errors.append(f"目录存在重复路线 ID: {', '.join(sorted(duplicated))}")

        geometry_path = self.project_file(
            project_paths.resolve_path(
                project_paths.route_module / GEOMETRY_RELATIVE, "路线几何"
            ),
            "路线几何",
        )
        geometry = self.read_json(geometry_path, "路线几何")
        geometry_ids = self._geometry_ids(geometry, errors)

        if geometry_ids is not None and catalog_ids:
            catalog_set, geometry_set = set(catalog_ids), set(geometry_ids)
            missing = sorted(catalog_set - geometry_set)
            unexpected = sorted(geometry_set - catalog_set)
            if missing:
                errors.append(f"GeoJSON 缺少路线: {', '.join(missing)}")
            if unexpected:
                errors.append(f"GeoJSON 含目录外路线: {', '.join(unexpected)}")

        accepted = sum(1 for item in catalog if isinstance(item, dict) and item.get("validation_status") == "accepted")
        if catalog and accepted != len([item for item in catalog if isinstance(item, dict)]):
            warnings.append(f"validation_status 非 accepted 的路线 {len(catalog) - accepted} 条")
        return errors, warnings

    def _geometry_ids(self, geometry: Any, errors: list[str]) -> list[str] | None:
        if not isinstance(geometry, dict) or geometry.get("type") != "FeatureCollection":
            errors.append(f"{GEOMETRY_RELATIVE} 必须是 GeoJSON FeatureCollection")
            return None
        features = geometry.get("features")
        if not isinstance(features, list):
            errors.append(f"{GEOMETRY_RELATIVE}.features 必须是数组")
            return None
        ids: list[str] = []
        for index, feature in enumerate(features):
            where = f"features[{index}]"
            if not isinstance(feature, dict):
                errors.append(f"{where} 必须是对象")
                continue
            properties = feature.get("properties") or {}
            route_id = properties.get("route_id") if isinstance(properties, dict) else None
            if not isinstance(route_id, str) or not route_id:
                errors.append(f"{where}.properties.route_id 缺失")
                continue
            ids.append(route_id)
            shape = feature.get("geometry") or {}
            if not isinstance(shape, dict) or shape.get("type") != "LineString":
                errors.append(f"{where}.geometry.type 必须是 LineString")
                continue
            coordinates = shape.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                errors.append(f"{where}.geometry.coordinates 至少需要 2 个点")
                continue
            for point in coordinates:
                if (
                    not isinstance(point, list)
                    or len(point) < 2
                    or not isinstance(point[0], (int, float))
                    or not isinstance(point[1], (int, float))
                    or not -180.0 <= point[0] <= 180.0
                    or not -90.0 <= point[1] <= 90.0
                ):
                    errors.append(f"{where}.geometry.coordinates 含非法坐标")
                    break
        duplicated = {route_id for route_id in ids if ids.count(route_id) > 1}
        if duplicated:
            errors.append(f"GeoJSON 存在重复路线 ID: {', '.join(sorted(duplicated))}")
        return ids

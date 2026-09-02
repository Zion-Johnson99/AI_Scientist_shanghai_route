"""生成工程的静态功能契约评分与安全检查。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..models import StrictModel
from .models import REQUIRED_PROJECT_ROOTS, ValidationIssue, normalize_source_path

CONTRACT_THRESHOLD = 85
_MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
_TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|/(?:home|users|tmp|etc|var|opt|srv)/)"
)
_TRAVERSAL_RE = re.compile(r"(?:^|[\"'\s(])\.\.[\\/]", re.MULTILINE)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|dashscope)-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(
        r"(?i)[\"']?(?:api[_-]?key|secret|token|password)[\"']?\s*[:=]\s*"
        r"[\"']([^\"']{8,})[\"']"
    ),
)
_SAFE_SECRET_MARKERS = ("placeholder", "example", "test", "your_", "changeme", "xxx")


class ContractCheck(StrictModel):
    name: str
    label: str
    weight: int = Field(ge=0)
    earned: int = Field(ge=0)
    passed: bool
    critical: bool = False
    detail: str
    evidence: list[str] = Field(default_factory=list)


class FunctionalContractReport(StrictModel):
    score: int = Field(ge=0, le=100)
    threshold: int = CONTRACT_THRESHOLD
    passed: bool
    provenance: Literal["qwen", "offline_fixture"]
    checks: list[ContractCheck]


class FunctionalContractValidator:
    """对生成源码做 100 分静态验收，并把未达标项交给修复循环。"""

    def __init__(
        self,
        *,
        threshold: int = CONTRACT_THRESHOLD,
        provenance: Literal["qwen", "offline_fixture"] = "qwen",
    ) -> None:
        if not 0 <= threshold <= 100:
            raise ValueError("threshold 需位于 0 到 100")
        self.threshold = threshold
        self.provenance: Literal["qwen", "offline_fixture"] = provenance
        self.last_report: FunctionalContractReport | None = None

    def __call__(self, source_root: Path) -> list[ValidationIssue]:
        report = self.evaluate(source_root)
        self.last_report = report
        if report.passed:
            return []
        return [
            ValidationIssue(
                check=check.name,
                summary=f"{check.label}未通过",
                details=f"{check.detail}；本项 {check.earned}/{check.weight} 分",
                files=self._valid_evidence_paths(check.evidence),
            )
            for check in report.checks
            if not check.passed
        ]

    def evaluate(self, source_root: Path) -> FunctionalContractReport:
        root = Path(source_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        texts, boundary_violations = self._read_source_texts(root)
        combined = "\n".join(texts.values()).lower()

        roots_present = [name for name in REQUIRED_PROJECT_ROOTS if (root / name).is_dir()]
        environment_files = self._matching_files(texts, "weather_api_data/")
        route_files = self._matching_files(texts, "xuhui_route_builder/")
        evaluation_files = self._matching_files(texts, "evaluation_model_qwen/")
        web_files = [path for path in route_files if "/web/" in f"/{path}"]
        route_count, route_catalogs = self._route_count(root)
        route_catalog_path = root / "xuhui_route_builder" / "data" / "web" / "route_catalog.json"
        route_geojson_path = root / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"
        environment_dashboard_path = (
            root / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json"
        )
        score_bridge_path = (
            root
            / "Qwen-Harness"
            / "src"
            / "qwen_harness"
            / "adapters"
            / "evaluation_score_candidates.py"
        )
        weights_path = root / "evaluation_model_qwen" / "config" / "default_weights.json"
        evaluation_pyproject = root / "evaluation_model_qwen" / "pyproject.toml"
        route_contract_ok = self._route_contract(route_catalog_path, route_geojson_path)
        environment_contract_ok = self._environment_contract(environment_dashboard_path)

        environment_ok = environment_contract_ok and bool(environment_files) and any(
            marker in "\n".join(texts[path].lower() for path in environment_files)
            for marker in ("get_environment", "/api/v1/environment", "pm2.5", "aqi")
        )
        route_ok = route_contract_ok and bool(route_files) and any(
            marker in "\n".join(texts[path].lower() for path in route_files)
            for marker in ("generate_route", "build_route", "/api/v1/routes")
        )
        evaluation_text = "\n".join(texts[path].lower() for path in evaluation_files)
        evaluation_ok = (
            score_bridge_path.is_file()
            and weights_path.is_file()
            and evaluation_pyproject.is_file()
            and "/health" in evaluation_text
            and any(
            marker in evaluation_text
            for marker in ("/api/v1/recommendations", "/api/v1/score", "score_candidates")
            )
        )
        map_structure_ok = any(path.lower().endswith("/web/index.html") for path in web_files) and any(
            marker in "\n".join(texts[path].lower() for path in web_files)
            for marker in ("id=\"map\"", "id='map'", "amap", "leaflet", "maplibre")
        )
        web_runtime_ok = self._web_runtime_contract(texts, web_files)
        map_ok = map_structure_ok and web_runtime_ok
        interaction_markers = (
            "addeventlistener",
            "route-select",
            "filter",
            "qwen",
        )
        interaction_hits = [marker for marker in interaction_markers if marker in combined]
        launchers = [
            path
            for path in texts
            if path.lower().endswith(("launch-local.ps1", "start-local.ps1", "start-local.sh"))
        ]
        launcher_ok = bool(launchers) and any(
            marker in "\n".join(texts[path].lower() for path in launchers)
            for marker in ("python", "uv run", "npm")
        )
        tests = [
            path
            for path in texts
            if "/tests/" in f"/{path}" or Path(path).name.startswith("test_") or ".test." in path
        ]
        production_texts = {
            path: text
            for path, text in texts.items()
            if "/tests/" not in f"/{path}" and not Path(path).name.startswith("test_")
        }
        absolute_hits = [
            path for path, text in production_texts.items() if _ABSOLUTE_PATH_RE.search(text)
        ]
        traversal_hits = [
            path for path, text in production_texts.items() if _TRAVERSAL_RE.search(text)
        ]
        sensitive_hits = [path for path, text in texts.items() if self._contains_secret(text)]

        checks = [
            self._check(
                "project_roots",
                "四源码目录",
                8,
                len(roots_present) == len(REQUIRED_PROJECT_ROOTS),
                f"已找到 {len(roots_present)}/{len(REQUIRED_PROJECT_ROOTS)} 个目录",
                roots_present,
            ),
            self._check(
                "environment_interface",
                "环境数据接口",
                10,
                environment_ok,
                "已检测环境数据入口" if environment_ok else "缺少可识别的环境数据入口",
                [
                    *environment_files,
                    "xuhui_route_builder/data/web/environment_dashboard.json",
                ],
            ),
            self._check(
                "route_generation",
                "路线生成能力",
                10,
                route_ok,
                "已检测路线生成入口" if route_ok else "缺少可识别的路线生成入口",
                [
                    *route_files,
                    "xuhui_route_builder/data/web/route_catalog.json",
                    "xuhui_route_builder/data/web/xuhui_routes.geojson",
                ],
            ),
            self._check(
                "evaluation_api",
                "评价 API 与健康端点",
                12,
                evaluation_ok,
                "评价与健康端点齐全" if evaluation_ok else "缺少评价入口或 /health 端点",
                [
                    *evaluation_files,
                    "Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py",
                    "evaluation_model_qwen/config/default_weights.json",
                    "evaluation_model_qwen/pyproject.toml",
                ],
            ),
            self._check(
                "route_catalog_90",
                "90 条路线",
                12,
                route_count == 90 and route_contract_ok,
                f"检测到 {route_count} 条结构合格路线",
                [*route_catalogs, "xuhui_route_builder/data/web/route_catalog.json"],
            ),
            self._check(
                "map_web",
                "地图网页",
                12,
                map_ok,
                "地图容器、模块入口与数据路径齐全"
                if map_ok
                else "地图入口、ES 模块加载或 data/web 路径无效",
                web_files,
                critical=True,
            ),
            self._check(
                "core_interactions",
                "核心交互",
                8,
                len(interaction_hits) >= 3,
                f"检测到 {len(interaction_hits)}/4 类交互标记",
                web_files,
            ),
            self._check(
                "local_launcher",
                "本地启动",
                8,
                launcher_ok,
                "本地启动脚本已就绪" if launcher_ok else "缺少可识别的本地启动脚本",
                launchers,
            ),
            self._check(
                "tests_present",
                "自动化测试",
                8,
                bool(tests),
                f"检测到 {len(tests)} 个测试文件",
                tests,
            ),
            self._check(
                "absolute_paths",
                "绝对路径检查",
                3,
                not absolute_hits,
                "未发现机器绝对路径" if not absolute_hits else "发现机器绝对路径",
                absolute_hits,
                critical=True,
            ),
            self._check(
                "sensitive_information",
                "敏感信息检查",
                5,
                not sensitive_hits,
                "未发现硬编码凭据" if not sensitive_hits else "发现疑似硬编码凭据",
                sensitive_hits,
                critical=True,
            ),
            self._check(
                "path_boundary",
                "源码路径边界",
                2,
                not boundary_violations,
                "全部文件位于源码根目录" if not boundary_violations else "发现越界链接或文件",
                boundary_violations,
                critical=True,
            ),
            self._check(
                "path_traversal",
                "路径穿越检查",
                2,
                not traversal_hits,
                "未发现父级穿越片段" if not traversal_hits else "发现父级穿越片段",
                traversal_hits,
                critical=True,
            ),
        ]
        score = sum(check.earned for check in checks)
        critical_passed = all(check.passed for check in checks if check.critical)
        return FunctionalContractReport(
            score=score,
            threshold=self.threshold,
            passed=score >= self.threshold and critical_passed,
            provenance=self.provenance,
            checks=checks,
        )

    @staticmethod
    def _check(
        name: str,
        label: str,
        weight: int,
        passed: bool,
        detail: str,
        evidence: list[str],
        *,
        critical: bool = False,
    ) -> ContractCheck:
        return ContractCheck(
            name=name,
            label=label,
            weight=weight,
            earned=weight if passed else 0,
            passed=passed,
            critical=critical,
            detail=detail,
            evidence=sorted(set(evidence)),
        )

    @staticmethod
    def _matching_files(texts: dict[str, str], prefix: str) -> list[str]:
        return [path for path in texts if path.startswith(prefix)]

    @staticmethod
    def _web_runtime_contract(texts: dict[str, str], web_files: list[str]) -> bool:
        index_path = next(
            (path for path in web_files if path.lower().endswith("/web/index.html")),
            None,
        )
        if index_path is None:
            return False
        index_text = texts[index_path]
        javascript = {
            path: texts[path]
            for path in web_files
            if Path(path).suffix.lower() in {".js", ".mjs"}
        }
        uses_modules = any(
            re.search(r"(?m)^\s*(?:import|export)\b", text) for text in javascript.values()
        )
        script_tags = re.findall(r"<script\b[^>]*>", index_text, flags=re.IGNORECASE)
        module_entry_ok = not uses_modules or any(
            re.search(r"\btype\s*=\s*['\"]module['\"]", tag, flags=re.IGNORECASE)
            and re.search(r"\bsrc\s*=\s*['\"][^'\"]*(?:main|app)\.js['\"]", tag, flags=re.IGNORECASE)
            for tag in script_tags
        )
        loads_route_data = any("route_catalog.json" in text for text in javascript.values())
        data_path_ok = not loads_route_data or any(
            re.search(r"['\"](?:\.\./|/)data/web/", text) for text in javascript.values()
        )
        return module_entry_ok and data_path_ok

    @staticmethod
    def _valid_evidence_paths(paths: list[str]) -> list[str]:
        valid: list[str] = []
        for path in paths:
            try:
                valid.append(normalize_source_path(path))
            except ValueError:
                continue
        return valid

    @staticmethod
    def _read_source_texts(root: Path) -> tuple[dict[str, str], list[str]]:
        texts: dict[str, str] = {}
        violations: list[str] = []
        for path in root.rglob("*"):
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                violations.append(path.relative_to(root).as_posix())
                continue
            is_junction = getattr(path, "is_junction", lambda: False)()
            if (path.is_symlink() or is_junction) and resolved != path.absolute():
                violations.append(path.relative_to(root).as_posix())
                continue
            if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
                    continue
                texts[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        return texts, violations

    @staticmethod
    def _contains_secret(text: str) -> bool:
        for pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1) if match.lastindex else match.group(0)
                if not any(marker in value.lower() for marker in _SAFE_SECRET_MARKERS):
                    return True
        return False

    @staticmethod
    def _route_count(root: Path) -> tuple[int, list[str]]:
        maximum = 0
        catalogs: list[str] = []
        route_root = root / "xuhui_route_builder"
        if not route_root.is_dir():
            return maximum, catalogs
        for path in route_root.rglob("*.json"):
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
                if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            count = FunctionalContractValidator._count_routes(data)
            if count:
                catalogs.append(path.relative_to(root).as_posix())
                maximum = max(maximum, count)
        return maximum, catalogs

    @staticmethod
    def _count_routes(node: object) -> int:
        if isinstance(node, dict):
            routes = node.get("routes")
            direct = len(routes) if isinstance(routes, list) else 0
            nested = max(
                (FunctionalContractValidator._count_routes(value) for value in node.values()),
                default=0,
            )
            return max(direct, nested)
        if isinstance(node, list):
            route_like = sum(
                1
                for item in node
                if isinstance(item, dict) and ("route_id" in item or "geometry" in item)
            )
            nested = max(
                (FunctionalContractValidator._count_routes(item) for item in node),
                default=0,
            )
            return max(route_like, nested)
        return 0

    @staticmethod
    def _route_contract(catalog_path: Path, geojson_path: Path) -> bool:
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(catalog, list) or len(catalog) != 90:
            return False
        required = {"route_id", "route_name", "route_mode", "validation_status", "geometry_status"}
        if any(not isinstance(item, dict) or not required.issubset(item) for item in catalog):
            return False
        mode_counts = {
            mode: sum(1 for item in catalog if item.get("route_mode") == mode)
            for mode in ("walk", "run", "bike")
        }
        if mode_counts != {"walk": 30, "run": 30, "bike": 30}:
            return False
        features = geojson.get("features") if isinstance(geojson, dict) else None
        return geojson.get("type") == "FeatureCollection" and isinstance(features, list) and len(features) == 90

    @staticmethod
    def _environment_contract(path: Path) -> bool:
        try:
            dashboard = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(dashboard, dict):
            return False
        if any(not isinstance(dashboard.get(key), dict) for key in ("metadata", "current", "forecast", "routes")):
            return False
        routes = dashboard["routes"]
        items = routes.get("items")
        if not isinstance(items, list) or len(items) != 90 or routes.get("count") != 90:
            return False
        return all(
            isinstance(item, dict)
            and isinstance(item.get("route_id"), str)
            and isinstance(item.get("pm2_5"), dict)
            and isinstance(item.get("noise"), dict)
            and isinstance(item.get("pollen_daily"), list)
            for item in items
        )

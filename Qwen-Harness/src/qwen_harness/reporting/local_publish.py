"""构建只包含本轮生成成果的本地交付包。

源码唯一输入为 ``<run-dir>/workspace/source``。发布过程不会读取仓库中的
现有四个工程，也不会写回任何外部模块或网页目录。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

REQUIRED_SOURCE_MODULES = (
    "Qwen-Harness",
    "evaluation_model_qwen",
    "weather_api_data",
    "xuhui_route_builder",
)
REPORT_PUBLISH_NAMES = {
    "full_run_report.md": "完整运行报告.md",
    "scientific_plan.md": "科学计划.md",
    "experiment_report.md": "实验报告.md",
}
WEB_PAYLOAD_NAME = "research_harness_latest.json"
EXCLUDED_GENERATED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "runtime",
    "test-results",
}
SENSITIVE_FILENAMES = {
    ".env",
    "local-amap-config.js",
    "local-tencent-config.js",
}
SENSITIVE_NAME_PARTS = ("credential", "secret", "token")

LAUNCH_SCRIPT = """Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$productRoot = Join-Path $PSScriptRoot "local-product"
$indexPath = Join-Path $productRoot "web\\index.html"
$apiRoot = Join-Path $PSScriptRoot "source\\evaluation_model_qwen"
$apiProjectPath = Join-Path $apiRoot "pyproject.toml"
$apiHealthUrl = "http://127.0.0.1:8124/api/v1/health"
$apiProcess = $null
$apiServiceProcessId = $null

if (-not (Test-Path -LiteralPath $indexPath)) {
    throw "本地地图产品不完整: $indexPath"
}
if (-not (Test-Path -LiteralPath $apiProjectPath)) {
    throw "本轮生成的推荐服务缺少 pyproject.toml: $apiProjectPath；无法启动 uvicorn。"
}

function Test-ApiReady {
    try {
        $response = Invoke-WebRequest -Uri $apiHealthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

$apiReady = Test-ApiReady
try {
    if (-not $apiReady) {
        $uv = Get-Command uv -ErrorAction Stop
        $env:EVALUATION_MODEL_QWEN_OFFLINE = "1"
        $env:EVALUATION_MODEL_QWEN_ALLOWED_ORIGINS = "http://127.0.0.1:8130,http://localhost:8130"
        $env:EVALUATION_MODEL_QWEN_AUDIT_ROOT = Join-Path $apiRoot "runtime\\recommendations"
        $stdoutLog = Join-Path $PSScriptRoot "checks\\local-api.stdout.log"
        $stderrLog = Join-Path $PSScriptRoot "checks\\local-api.stderr.log"
        $apiArgs = @(
            "run", "--project", "`"$apiRoot`"", "uvicorn", "evaluation_model_qwen.api:app",
            "--host", "127.0.0.1", "--port", "8124"
        )
        $apiProcess = Start-Process -FilePath $uv.Source -ArgumentList $apiArgs `
            -WorkingDirectory $apiRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
            if ($apiProcess.HasExited) {
                break
            }
            if (Test-ApiReady) {
                $apiReady = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }
    }
    if ($apiReady) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort 8124 -ErrorAction Stop |
            Select-Object -First 1
        $apiServiceProcessId = $listener.OwningProcess
        Write-Host "本地推荐服务已就绪: $apiHealthUrl"
    }
    else {
        Write-Warning "本轮生成的推荐服务健康检查未就绪: $apiHealthUrl；网页继续以无推荐服务模式启动；查看 $stderrLog"
    }

    Write-Host "本地地图已就绪: http://127.0.0.1:8130/web/"
    Write-Host "按 Ctrl+C 停止服务。"
    python -m http.server 8130 --bind 127.0.0.1 --directory $productRoot
}
finally {
    if ($null -ne $apiServiceProcessId) {
        Stop-Process -Id $apiServiceProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -Force
    }
}
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_publishable(relative: Path) -> bool:
    lowered_parts = {part.lower() for part in relative.parts}
    name = relative.name.lower()
    if lowered_parts & EXCLUDED_GENERATED_PARTS or name in SENSITIVE_FILENAMES:
        return False
    return not any(marker in name for marker in SENSITIVE_NAME_PARTS)


def _publishable_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not _is_publishable(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"生成成果包含符号链接，拒绝发布: {path}")
        if path.is_file():
            yield path


def _require_generated_tree(root: Path, label: str) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(f"本轮生成{label}目录不存在: {root}")
    files = list(_publishable_files(root))
    if not files:
        raise FileNotFoundError(f"本轮生成{label}目录没有可发布文件: {root}")
    return files


def _copy_generated_tree(source: Path, target: Path) -> int:
    files = list(_publishable_files(source))
    target.mkdir(parents=True, exist_ok=True)
    for source_file in files:
        destination = target / source_file.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)
    return len(files)


def _generated_inputs(run_dir: Path) -> tuple[Path, Path, Path]:
    source_root = run_dir / "workspace" / "source"
    _require_generated_tree(source_root, "源码")
    for module in REQUIRED_SOURCE_MODULES:
        _require_generated_tree(source_root / module, f"源码模块 {module}")

    route_root = source_root / "xuhui_route_builder"
    web_root = route_root / "web"
    web_data_root = route_root / "data" / "web"
    if not (web_root / "index.html").is_file():
        raise FileNotFoundError(f"本轮生成网页入口不存在: {web_root / 'index.html'}")
    _require_generated_tree(web_root, "网页")
    _require_generated_tree(web_data_root, "网页数据")
    return source_root, web_root, web_data_root


def _required_report_sources(run_dir: Path) -> dict[Path, str]:
    reports_root = run_dir / "reports"
    result: dict[Path, str] = {}
    for source_name, publish_name in REPORT_PUBLISH_NAMES.items():
        source = reports_root / source_name
        if not source.is_file():
            raise FileNotFoundError(f"本轮生成报告 {publish_name} 不存在: {source}")
        result[source] = publish_name
    return result


def _read_staged_web_payload(publish_root: Path) -> bytes | None:
    payload_path = publish_root / WEB_PAYLOAD_NAME
    if not payload_path.exists():
        return None
    if payload_path.is_symlink():
        raise ValueError(f"web_payload 包含符号链接，拒绝发布: {payload_path}")
    if not payload_path.is_file():
        raise ValueError(f"web_payload 路径并非文件: {payload_path}")
    try:
        payload_bytes = payload_path.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"web_payload JSON 无效: {payload_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"web_payload 顶层结构应为 JSON 对象: {payload_path}")
    return payload_bytes


def _copy_reports(run_dir: Path, target: Path) -> None:
    report_sources = _required_report_sources(run_dir)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for source, publish_name in report_sources.items():
        shutil.copy2(source, target / publish_name)


def _prepare_full_report(context: "WorkflowContext") -> None:
    """在本地网页生成后刷新引擎审计报告。"""
    try:
        from .full_run_report import write_full_run_report
    except ModuleNotFoundError as exc:
        expected = f"{__package__}.full_run_report"
        if exc.name != expected:
            raise
        return
    write_full_run_report(context)


def _copy_checks(context: "WorkflowContext", target: Path) -> None:
    source = context.run_dir / "checks"
    if target.exists():
        shutil.rmtree(target)
    if source.is_dir():
        _copy_generated_tree(source, target)
        return
    target.mkdir(parents=True)
    summary = {
        "run_id": context.run_id,
        "status": "not_recorded",
        "message": "本次运行尚无独立测试、类型检查或浏览器验收记录。",
    }
    (target / "checks_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_manifest(publish_root: Path, source_counts: dict[str, int]) -> Path:
    entries: list[dict[str, Any]] = []
    for path in sorted(publish_root.rglob("*")):
        if not path.is_file() or path.name == "source_manifest.json":
            continue
        entries.append(
            {
                "path": path.relative_to(publish_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest_path = publish_root / "source_manifest.json"
    manifest = {
        "schema_version": "1.0",
        "source_origin": "workspace/source",
        "source_file_counts": source_counts,
        "file_count": len(entries),
        "files": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def refresh_local_publish_metadata(context: "WorkflowContext") -> Path | None:
    """运行结束后把最终中文报告同步进已有交付包并刷新清单。"""
    publish_root = context.run_dir / "publish"
    manifest_path = publish_root / "source_manifest.json"
    if not manifest_path.is_file():
        return None
    previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_counts = previous_manifest.get("source_file_counts")
    source_counts = (
        {str(name): int(count) for name, count in raw_counts.items()}
        if isinstance(raw_counts, dict)
        else {}
    )
    _prepare_full_report(context)
    _copy_reports(context.run_dir, publish_root / "reports")
    return _write_manifest(publish_root, source_counts)


def build_local_publish(context: "WorkflowContext") -> dict[str, Any]:
    """生成 ``publish/`` 下的完整本地交付包。"""
    source_input, web_input, web_data_input = _generated_inputs(context.run_dir)
    _prepare_full_report(context)
    _required_report_sources(context.run_dir)

    publish_root = context.run_dir / "publish"
    staged_web_payload = _read_staged_web_payload(publish_root)
    if publish_root.exists():
        shutil.rmtree(publish_root)
    publish_root.mkdir(parents=True)

    source_root = publish_root / "source"
    source_counts = {
        module: _copy_generated_tree(source_input / module, source_root / module)
        for module in REQUIRED_SOURCE_MODULES
    }

    local_product = publish_root / "local-product"
    _copy_generated_tree(web_input, local_product / "web")
    local_web_data = local_product / "data" / "web"
    _copy_generated_tree(web_data_input, local_web_data)
    if staged_web_payload is not None:
        (local_web_data / WEB_PAYLOAD_NAME).write_bytes(staged_web_payload)
    _copy_checks(context, publish_root / "checks")
    _copy_reports(context.run_dir, publish_root / "reports")

    launch_path = publish_root / "launch-local.ps1"
    launch_path.write_text(LAUNCH_SCRIPT, encoding="utf-8-sig")
    manifest_path = _write_manifest(publish_root, source_counts)

    return {
        "publish_root": publish_root.relative_to(context.run_dir).as_posix(),
        "local_url": "http://127.0.0.1:8130/web/",
        "source_origin": source_input.relative_to(context.run_dir).as_posix(),
        "source_file_counts": source_counts,
        "manifest": manifest_path.relative_to(context.run_dir).as_posix(),
    }

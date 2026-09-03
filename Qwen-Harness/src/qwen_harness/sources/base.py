"""来源采集阶段与 SourceAdapter 基类（设计文档 01 §11.1、§13）。

``source_collection_stage`` 是 ``source_collection`` 阶段的冻结处理器：

- 在线且获得网络授权时，按 ``goal.seed_sources`` 与
  ``examples/source-manifest.json`` 采集本地 / 仓库 / PubMed / Crossref /
  HTTPS 五类来源，注册到 ``sources/source_registry.jsonl``。
- 离线或网络未授权时，从 ``examples/fixtures/sources/`` 读取固定来源，
  审计标记夹具来源；绝不伪造新的检索结果。
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..config import SourcePolicy, load_source_policy
from ..errors import InputContractError, SourceUnavailableError
from ..logging_utils import get_logger
from ..models import ExtractedDocument, SourceRecord, SourceRequest, StageResult

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

LOGGER = get_logger("sources.base")

FIXTURE_SOURCES_RELATIVE = Path("examples") / "fixtures" / "sources"
SOURCE_MANIFEST_RELATIVE = Path("examples") / "source-manifest.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 网络策略
# ---------------------------------------------------------------------------
def validate_https_url(
    url: str, policy: SourcePolicy, allowed_domains: list[str] | None = None
) -> str:
    """仅 HTTPS、拒绝含凭证 URL、限定允许域名；返回规范化 URL。"""
    parsed = urlparse(url)
    if policy.https_only and parsed.scheme != "https":
        raise InputContractError(f"仅允许 HTTPS 来源: {url}", suggested_action="改用 https:// 链接")
    if policy.reject_url_credentials and (
        parsed.username or parsed.password or "@" in parsed.netloc
    ):
        raise InputContractError(
            "来源 URL 含凭证信息，已拒绝", suggested_action="移除 URL 中的用户名/密码"
        )
    domains = allowed_domains if allowed_domains else policy.allowed_domains
    host = (parsed.hostname or "").lower()
    if domains and not any(host == d or host.endswith("." + d) for d in domains):
        raise InputContractError(
            f"域名不在允许清单内: {host}",
            suggested_action=f"允许域名见 config/source_policy.json（共 {len(domains)} 个）",
        )
    return url


class HttpFetcher:
    """受 source_policy 约束的最小 HTTP 客户端（限流、限量、可重试）。"""

    def __init__(self, policy: SourcePolicy, timeout_seconds: int = 30) -> None:
        self.policy = policy
        self.timeout = timeout_seconds
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        interval = self.policy.request_interval_seconds
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def get(self, url: str, *, accept: str = "text/html") -> bytes:
        import requests

        self._throttle()
        headers = {"User-Agent": self.policy.user_agent, "Accept": accept}
        last_error: Exception | None = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                response = requests.get(url, headers=headers, timeout=self.timeout, stream=True)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(2.0 * (attempt + 1), 8.0))
                continue
            finally:
                self._last_request_at = time.monotonic()
            if (
                response.status_code in (429, 500, 502, 503, 504)
                and attempt < self.policy.max_retries
            ):
                time.sleep(min(2.0 * (attempt + 1), 8.0))
                continue
            if response.status_code != 200:
                raise SourceUnavailableError(
                    f"来源请求失败: HTTP {response.status_code} {url}",
                    suggested_action="稍后重试或改用本地/离线来源",
                )
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(chunk_size=65536):
                received += len(chunk)
                if received > self.policy.max_download_bytes:
                    raise SourceUnavailableError(
                        f"来源超过大小限制 {self.policy.max_download_bytes} 字节: {url}",
                        suggested_action="改用摘要级来源或提高策略上限（需评审）",
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        raise SourceUnavailableError(
            f"来源请求重试耗尽: {url}: {last_error}",
            suggested_action="稍后重试；持续失败请改用本地/离线来源",
        )


# ---------------------------------------------------------------------------
# SourceAdapter 基类
# ---------------------------------------------------------------------------
class SourceAdapter:
    """来源适配器基类：``collect`` 返回注册记录，``extract_text`` 抽取文本。"""

    source_type: str = "local_file"

    def __init__(
        self, *, repo_root: Path, policy: SourcePolicy, network_enabled: bool = False
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.policy = policy
        self.network_enabled = network_enabled
        self.fetcher = HttpFetcher(policy)

    def require_network(self) -> None:
        if not self.network_enabled:
            raise SourceUnavailableError(
                f"{self.source_type} 来源需要网络授权",
                suggested_action="使用 --allow-network 并配置 QWEN_HARNESS_NETWORK_ENABLED=1，或改用离线来源",
            )

    def boundary_path(self, candidate: str) -> Path:
        resolved = Path(candidate)
        resolved = (
            (self.repo_root / resolved).resolve()
            if not resolved.is_absolute()
            else resolved.resolve()
        )
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise InputContractError(
                f"来源路径越出仓库边界: {candidate}",
                suggested_action="本地来源必须位于仓库根目录内",
            ) from exc
        return resolved

    def collect(self, request: SourceRequest) -> list[SourceRecord]:
        raise NotImplementedError

    def extract_text(self, record: SourceRecord) -> ExtractedDocument:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 固定夹具来源（离线 / 未授权降级）
# ---------------------------------------------------------------------------
def fixture_sources_dir(harness_root: Path) -> Path:
    return Path(harness_root) / FIXTURE_SOURCES_RELATIVE


def load_fixture_sources(harness_root: Path) -> tuple[list[SourceRecord], dict[str, str]]:
    """读取固定来源元数据与文本；SHA256 不一致即夹具损坏。"""
    directory = fixture_sources_dir(harness_root)
    if not directory.is_dir():
        raise InputContractError(
            f"离线固定来源目录缺失: {directory}",
            suggested_action="恢复 examples/fixtures/sources/ 目录",
        )
    records: list[SourceRecord] = []
    texts: dict[str, str] = {}
    for meta_path in sorted(directory.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InputContractError(f"固定来源元数据不可读: {meta_path.name}: {exc}") from exc
        try:
            record = SourceRecord.model_validate(meta)
        except Exception as exc:  # pydantic ValidationError
            raise InputContractError(
                f"固定来源 {meta_path.name} 不符合 SourceRecord 契约: {exc}"
            ) from exc
        text_path = meta_path.with_suffix(".txt")
        if not text_path.is_file():
            raise InputContractError(
                f"固定来源缺少配套文本: {text_path.name}",
                suggested_action="每个 <source_id>.json 必须有同名 <source_id>.txt",
            )
        text = text_path.read_text(encoding="utf-8")
        if sha256_bytes(text.encode("utf-8")) != record.sha256:
            raise InputContractError(
                f"固定来源文本与元数据 SHA256 不一致: {record.source_id}",
                suggested_action="夹具已损坏，恢复 examples/fixtures/sources/ 原始内容",
            )
        records.append(record)
        texts[record.source_id] = text
    if not records:
        raise InputContractError(f"固定来源目录为空: {directory}")
    return records, texts


# ---------------------------------------------------------------------------
# 清单与种子解析
# ---------------------------------------------------------------------------
def load_source_manifest(harness_root: Path) -> list[dict[str, Any]]:
    path = Path(harness_root) / SOURCE_MANIFEST_RELATIVE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputContractError(f"source-manifest.json 不可解析: {exc}") from exc
    entries = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise InputContractError("source-manifest.json 必须包含 sources 列表")
    return entries


def classify_seed(seed: str) -> tuple[str, str]:
    """把种子字符串归类为 (来源类型, 规范化值)。"""
    seed = seed.strip()
    if seed.startswith("https://") or seed.startswith("http://"):
        return "https_url", seed
    if seed.lower().startswith("doi:"):
        return "crossref", seed[4:].strip()
    if seed.lower().startswith("pmid:"):
        return "pubmed", seed[5:].strip()
    if seed.lower().startswith("repo:"):
        return "repository_file", seed[5:].strip()
    return "local_file", seed


# ---------------------------------------------------------------------------
# 阶段处理器
# ---------------------------------------------------------------------------
def _collect_online(context: "WorkflowContext", policy: SourcePolicy) -> StageResult:
    from .crossref import CrossrefSource
    from .local_files import LocalFileSource
    from .pubmed import PubMedSource
    from .repository import RepositorySource
    from .web import HttpsSource

    network_ok = bool(context.options.allow_network and context.settings.network_enabled)
    adapters: dict[str, SourceAdapter] = {
        "local_file": LocalFileSource(
            repo_root=context.repo_root, policy=policy, network_enabled=network_ok
        ),
        "repository_file": RepositorySource(
            repo_root=context.repo_root, policy=policy, network_enabled=network_ok
        ),
        "pubmed": PubMedSource(
            repo_root=context.repo_root, policy=policy, network_enabled=network_ok
        ),
        "crossref": CrossrefSource(
            repo_root=context.repo_root, policy=policy, network_enabled=network_ok
        ),
        "https_url": HttpsSource(
            repo_root=context.repo_root, policy=policy, network_enabled=network_ok
        ),
    }

    entries: list[dict[str, Any]] = list(load_source_manifest(context.harness_root))
    for seed in context.goal.seed_sources:
        kind, value = classify_seed(seed)
        key = {"crossref": "doi", "pubmed": "pmid", "https_url": "url"}.get(kind, "local_path")
        key = "repo_path" if kind == "repository_file" else key
        entries.append({"source_type": kind, key: value, "seed": seed})

    collected: list[SourceRecord] = []
    extracted: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    network_skipped = 0
    for entry in entries:
        kind = str(entry.get("source_type", ""))
        adapter = adapters.get(kind)
        if adapter is None:
            warnings.append(f"未知来源类型已跳过: {kind}")
            continue
        if kind in ("pubmed", "crossref", "https_url") and not network_ok:
            network_skipped += 1
            continue
        request = SourceRequest(
            terms=[str(entry["terms"])] if entry.get("terms") else [],
            source_types=[kind],  # type: ignore[list-item]
            max_results=10,
            allowed_domains=list(policy.allowed_domains),
            local_paths=[str(entry["local_path"])] if entry.get("local_path") else [],
            notes=str(
                entry.get("doi")
                or entry.get("pmid")
                or entry.get("url")
                or entry.get("repo_path")
                or ""
            ),
        )
        try:
            records = adapter.collect(request)
        except SourceUnavailableError as exc:
            warnings.append(f"{kind} 采集失败: {exc.message}")
            continue
        except InputContractError as exc:
            warnings.append(f"{kind} 来源被拒绝: {exc.message}")
            continue
        for record in records:
            collected.append(record)
            context.append_source(record)
            try:
                document = adapter.extract_text(record)
                extracted[record.source_id] = document.model_dump(mode="json")
            except InputContractError as exc:
                warnings.append(f"{record.source_id} 文本抽取停止: {exc.message}")

    if network_skipped and not collected:
        LOGGER.warning("网络来源未获授权且无本地来源，降级为离线固定来源")
        return _collect_offline(context, policy, degraded=True)
    if not collected:
        raise SourceUnavailableError(
            "来源采集未得到任何可用来源",
            suggested_action="检查 seed_sources / source-manifest.json，或使用 --offline",
        )
    if network_skipped:
        warnings.append(f"{network_skipped} 个网络来源因未获授权被跳过（--allow-network）")
    context.store.write_json_atomic("sources/extracted_texts.json", extracted)
    verified = sum(1 for record in collected if record.verification_status == "verified")
    return StageResult(
        stage="source_collection",
        status="passed",
        summary=f"采集来源 {len(collected)} 个（已验证 {verified}）",
        output={
            "source_count": len(collected),
            "source_ids": [record.source_id for record in collected],
            "verified_count": verified,
            "network_enabled": network_ok,
            "network_skipped": network_skipped,
        },
        artifacts=["sources/source_registry.jsonl", "sources/extracted_texts.json"],
        warnings=warnings,
    )


def _collect_offline(
    context: "WorkflowContext", policy: SourcePolicy, degraded: bool = False
) -> StageResult:
    records, texts = load_fixture_sources(context.harness_root)
    extracted: dict[str, dict[str, Any]] = {}
    for record in records:
        context.append_source(record)
        text = texts[record.source_id]
        document = ExtractedDocument(
            source_id=record.source_id,
            pages=[text],
            page_count=1,
            total_chars=len(text),
            sha256=record.sha256,
            requires_ocr=False,
            note="离线固定来源文本（夹具）",
        )
        extracted[record.source_id] = document.model_dump(mode="json")
    context.store.write_json_atomic("sources/extracted_texts.json", extracted)
    context.audit_extras["fixture_source"] = FIXTURE_SOURCES_RELATIVE.as_posix()
    context.audit_extras["offline_fixture"] = True
    warnings = ["离线模式：来源全部来自固定夹具，未发起任何网络检索"]
    if degraded:
        warnings.append("网络来源未获授权，已降级为离线固定来源")
    verified = sum(1 for record in records if record.verification_status == "verified")
    return StageResult(
        stage="source_collection",
        status="passed",
        summary=f"离线固定来源 {len(records)} 个（已验证 {verified}）",
        output={
            "source_count": len(records),
            "source_ids": [record.source_id for record in records],
            "verified_count": verified,
            "network_enabled": False,
            "fixture": True,
        },
        artifacts=["sources/source_registry.jsonl", "sources/extracted_texts.json"],
        warnings=warnings,
    )


def source_collection_stage(context: "WorkflowContext") -> StageResult:
    """source_collection 阶段：离线读夹具，在线按清单与种子采集。"""
    policy = load_source_policy(context.harness_root)
    if context.options.offline:
        return _collect_offline(context, policy)
    return _collect_online(context, policy)


__all__ = [
    "FIXTURE_SOURCES_RELATIVE",
    "HttpFetcher",
    "SourceAdapter",
    "classify_seed",
    "fixture_sources_dir",
    "load_fixture_sources",
    "load_source_manifest",
    "sha256_bytes",
    "source_collection_stage",
    "utc_now",
    "validate_https_url",
]

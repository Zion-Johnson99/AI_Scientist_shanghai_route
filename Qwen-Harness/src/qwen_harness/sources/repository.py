"""仓库文件来源（设计文档 01 §11.6）。

``RepositorySource`` 读取现有仓库中的 README、配置、数据 Schema 与审计
文件；任何代码事实都必须附文件路径与 SHA256。
"""

from __future__ import annotations

from ..errors import InputContractError
from ..logging_utils import get_logger
from ..models import ExtractedDocument, SourceRecord, SourceRequest
from .base import SourceAdapter, sha256_bytes, utc_now

LOGGER = get_logger("sources.repository")

#: 允许登记的仓库文件后缀（代码与数据契约文件）。
ALLOWED_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".csv",
    ".py",
    ".yaml",
    ".yml",
    ".geojson",
}
#: 文本类文件的单文件最大字符数（超过截断并记录）。
_MAX_CHARS = 200_000


class RepositorySource(SourceAdapter):
    """仓库内代码 / 配置 / 数据契约文件来源。"""

    source_type = "repository_file"

    def collect(self, request: SourceRequest) -> list[SourceRecord]:
        candidates: list[str] = []
        for raw_path in request.local_paths:
            candidates.append(raw_path)
        if request.notes:
            candidates.extend(item for item in request.notes.split(",") if item.strip())
        if not candidates:
            candidates = ["README.md"]
        records: list[SourceRecord] = []
        for raw_path in candidates:
            path = self.boundary_path(raw_path)
            if not path.is_file():
                raise InputContractError(
                    f"仓库来源文件不存在: {raw_path}",
                    suggested_action="检查 seed_sources 或清单中的 repo: 路径",
                )
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                raise InputContractError(
                    f"仓库来源类型不支持: {path.suffix}",
                    suggested_action=f"允许后缀: {', '.join(sorted(ALLOWED_SUFFIXES))}",
                )
            data = path.read_bytes()
            relative = path.relative_to(self.repo_root).as_posix()
            records.append(
                SourceRecord(
                    source_id=f"src-repo-{_slug(relative)}",
                    source_type="repository_file",
                    title=relative,
                    accessed_at=utc_now(),
                    sha256=sha256_bytes(data),
                    license_note=f"仓库文件 {relative}（事实附路径与 SHA256）",
                    verification_status="verified",
                    local_path=relative,
                )
            )
            if len(records) >= request.max_results:
                break
        return records

    def extract_text(self, record: SourceRecord) -> ExtractedDocument:
        if not record.local_path:
            raise InputContractError(f"仓库来源缺少 local_path: {record.source_id}")
        path = self.boundary_path(record.local_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > _MAX_CHARS
        if truncated:
            text = text[:_MAX_CHARS]
        return ExtractedDocument(
            source_id=record.source_id,
            pages=[text],
            page_count=1,
            total_chars=len(text),
            sha256=record.sha256,
            requires_ocr=False,
            note="超过字符上限已截断" if truncated else None,
        )


def _slug(relative: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in relative)[:48].strip("-")

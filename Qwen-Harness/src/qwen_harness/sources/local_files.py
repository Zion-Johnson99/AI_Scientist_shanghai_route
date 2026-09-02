"""本地文件来源（设计文档 01 §11.2）。

支持 ``.md``、``.txt``、``.json`` 与可搜索 ``.pdf``：

- 路径必须位于仓库根目录内（或用户显式允许的输入目录）。
- PDF 使用 ``pypdf`` 按页提取；记录页数、每页字符数与文件 SHA256。
- 页面无文本时标记 ``requires_ocr`` 并停止该来源（v1 不做 OCR）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import InputContractError
from ..logging_utils import get_logger
from ..models import ExtractedDocument, SourceRecord, SourceRequest
from .base import SourceAdapter, sha256_bytes, utc_now

LOGGER = get_logger("sources.local_files")

TEXT_SUFFIXES = {".md", ".txt", ".json"}
PDF_SUFFIX = ".pdf"
#: 单页至少应包含的可见字符数，低于该值视为无文本页。
_MIN_PAGE_CHARS = 20


class LocalFileSource(SourceAdapter):
    """仓库内文档来源；``extract_text`` 提供按页文本。"""

    source_type = "local_file"

    def collect(self, request: SourceRequest) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for raw_path in request.local_paths:
            path = self.boundary_path(raw_path)
            if not path.is_file():
                raise InputContractError(
                    f"本地来源不存在: {raw_path}",
                    suggested_action="检查 seed_sources 或 source-manifest.json 中的路径",
                )
            suffix = path.suffix.lower()
            if suffix not in TEXT_SUFFIXES and suffix != PDF_SUFFIX:
                raise InputContractError(
                    f"本地来源类型不支持: {suffix}",
                    suggested_action="v1 支持 .md/.txt/.json/可搜索 .pdf",
                )
            data = path.read_bytes()
            relative = path.relative_to(self.repo_root).as_posix()
            records.append(
                SourceRecord(
                    source_id=f"src-local-{path.stem}",
                    source_type="local_file",
                    title=path.stem,
                    accessed_at=utc_now(),
                    sha256=sha256_bytes(data),
                    license_note="仓库本地文件，仅用于科研分析",
                    verification_status="verified",
                    local_path=relative,
                )
            )
            if len(records) >= request.max_results:
                break
        return records

    def extract_text(self, record: SourceRecord) -> ExtractedDocument:
        if not record.local_path:
            raise InputContractError(f"本地来源缺少 local_path: {record.source_id}")
        path = self.boundary_path(record.local_path)
        suffix = path.suffix.lower()
        if suffix == PDF_SUFFIX:
            return self._extract_pdf(record, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return ExtractedDocument(
                source_id=record.source_id,
                pages=[],
                page_count=0,
                total_chars=0,
                sha256=record.sha256,
                requires_ocr=True,
                note="文件无可读文本，已停止该来源",
            )
        return ExtractedDocument(
            source_id=record.source_id,
            pages=[text],
            page_count=1,
            total_chars=len(text),
            sha256=record.sha256,
            requires_ocr=False,
        )

    def _extract_pdf(self, record: SourceRecord, path: Path) -> ExtractedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - pypdf 必装依赖
            raise InputContractError(
                "缺少 pypdf 依赖，无法解析 PDF 来源",
                suggested_action="执行 `uv sync` 安装依赖",
            ) from exc
        try:
            reader = PdfReader(str(path))
        except Exception as exc:  # pypdf 各类解析异常
            raise InputContractError(
                f"PDF 不可读（可能为扫描件）: {path.name}: {exc}",
                suggested_action="改用可搜索 PDF 或提供文本版来源",
            ) from exc
        pages: list[str] = []
        per_page_chars: list[int] = []
        requires_ocr = False
        for index, page in enumerate(reader.pages[: self.policy.pdf_max_pages], start=1):
            text = (page.extract_text() or "").strip()
            if len(text) < _MIN_PAGE_CHARS:
                requires_ocr = True
                LOGGER.warning("PDF 第 %d 页无有效文本，停止该来源: %s", index, path.name)
                break
            pages.append(text)
            per_page_chars.append(len(text))
        if requires_ocr or not pages:
            return ExtractedDocument(
                source_id=record.source_id,
                pages=[],
                page_count=len(reader.pages),
                total_chars=0,
                sha256=record.sha256,
                requires_ocr=True,
                note="存在无文本页，v1 停止该来源并报告（不做 OCR）",
            )
        return ExtractedDocument(
            source_id=record.source_id,
            pages=pages,
            page_count=len(reader.pages),
            total_chars=sum(per_page_chars),
            sha256=record.sha256,
            requires_ocr=False,
            note=f"每页字符数: {json.dumps(per_page_chars)}",
        )

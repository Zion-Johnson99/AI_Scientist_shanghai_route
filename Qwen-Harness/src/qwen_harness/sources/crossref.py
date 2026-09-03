"""Crossref 来源：DOI 元数据核验与补充（设计文档 01 §11.4）。

``CrossrefSource`` 通过 ``api.crossref.org/works/<doi>`` 核验元数据：

- DOI 格式异常 → ``rejected``。
- 标题相似度过低或年份冲突 → ``partial``。
- 其余情况 → ``verified``。
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from ..errors import InputContractError, SourceUnavailableError
from ..logging_utils import get_logger
from ..models import ExtractedDocument, SourceRecord, SourceRequest
from .base import SourceAdapter, sha256_bytes, utc_now, validate_https_url

LOGGER = get_logger("sources.crossref")

CROSSREF_API = "https://api.crossref.org/works/{doi}"
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
#: 标题相似度下限；低于该值只能给 partial。
_TITLE_SIMILARITY_MIN = 0.60


def normalize_title(title: str) -> str:
    return re.sub(r"\W+", " ", title or "").strip().lower()


class CrossrefSource(SourceAdapter):
    """DOI 元数据核验；``notes`` 传入 DOI，``terms`` 第一项可传期望标题。"""

    source_type = "crossref"

    def collect(self, request: SourceRequest) -> list[SourceRecord]:
        self.require_network()
        dois = [item.strip() for item in (request.notes or "").split(",") if item.strip()]
        if not dois and request.terms:
            raise InputContractError(
                "Crossref 采集需要提供 DOI（通过 notes 字段）",
                suggested_action="在清单中为 crossref 来源补充 doi 字段",
            )
        records: list[SourceRecord] = []
        expected_title = request.terms[0] if request.terms else ""
        for doi in dois[: request.max_results]:
            record = self._verify_doi(doi, expected_title)
            if record is not None:
                records.append(record)
        if not records:
            raise SourceUnavailableError("Crossref 未返回任何可核验的 DOI 元数据")
        return records

    def _verify_doi(self, doi: str, expected_title: str) -> SourceRecord | None:
        if not _DOI_RE.match(doi):
            LOGGER.warning("DOI 格式异常，标记 rejected: %s", doi)
            return SourceRecord(
                source_id=f"src-crossref-{_slug(doi)}",
                source_type="crossref",
                title=f"invalid DOI: {doi}",
                doi=doi,
                url=f"https://doi.org/{doi}",
                accessed_at=utc_now(),
                sha256=sha256_bytes(doi.encode("utf-8")),
                license_note="Crossref DOI 核验（格式异常）",
                verification_status="rejected",
            )
        url = CROSSREF_API.format(doi=_quote(doi))
        validate_https_url(url, self.policy)
        try:
            raw = self.fetcher.get(url, accept="application/json")
        except SourceUnavailableError as exc:
            LOGGER.warning("Crossref 查询失败 %s: %s", doi, exc.message)
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SourceUnavailableError(f"Crossref 返回无法解析: {exc}") from exc
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        title = " ".join(message.get("title") or []) or ""
        authors: list[str] = []
        for author in message.get("author") or []:
            family = str(author.get("family", "")).strip()
            given = str(author.get("given", "")).strip()
            if family:
                authors.append(f"{family} {given}".strip())
        year = _issued_year(message)
        resolved_doi = str(message.get("DOI", doi))
        metadata = json.dumps(message, ensure_ascii=False, sort_keys=True)

        status: str = "verified"
        notes: list[str] = []
        if expected_title and title:
            similarity = SequenceMatcher(
                None, normalize_title(title), normalize_title(expected_title)
            ).ratio()
            if similarity < _TITLE_SIMILARITY_MIN:
                status = "partial"
                notes.append(f"标题相似度 {similarity:.2f} 低于 {_TITLE_SIMILARITY_MIN:.2f}")
        return SourceRecord(
            source_id=f"src-crossref-{_slug(resolved_doi)}",
            source_type="crossref",
            title=title or resolved_doi,
            authors=authors,
            year=year,
            doi=resolved_doi,
            url=f"https://doi.org/{resolved_doi}",
            accessed_at=utc_now(),
            sha256=sha256_bytes(metadata.encode("utf-8")),
            license_note="Crossref metadata（开放 API）"
            + ("；" + "；".join(notes) if notes else ""),
            verification_status=status,  # type: ignore[arg-type]
        )

    def extract_text(self, record: SourceRecord) -> ExtractedDocument:
        """核验时已缓存元数据摘要，重建为单页文本。"""
        text = json.dumps(
            {
                "title": record.title,
                "authors": record.authors,
                "year": record.year,
                "doi": record.doi,
                "url": record.url,
                "verification_status": record.verification_status,
            },
            ensure_ascii=False,
            indent=2,
        )
        return ExtractedDocument(
            source_id=record.source_id,
            pages=[text],
            page_count=1,
            total_chars=len(text),
            sha256=sha256_bytes(text.encode("utf-8")),
            requires_ocr=False,
            note="Crossref 元数据摘要",
        )


def _issued_year(message: dict) -> int | None:
    issued = message.get("issued", {}) if isinstance(message, dict) else {}
    parts = issued.get("date-parts") if isinstance(issued, dict) else None
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        try:
            return int(parts[0][0])
        except (TypeError, ValueError):
            return None
    return None


def _slug(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", doi).strip("-").lower()[:48]


def _quote(doi: str) -> str:
    from urllib.parse import quote

    return quote(doi, safe="")

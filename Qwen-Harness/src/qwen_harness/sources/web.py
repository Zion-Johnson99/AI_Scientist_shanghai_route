"""HTTPS 页面来源（设计文档 01 §11.5）。

``HttpsSource`` 只访问 ``source_policy.allowed_domains`` 内的 HTTPS 页面，
用标准库 ``html.parser.HTMLParser`` 去除脚本、样式与导航噪声后登记文本。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from ..errors import InputContractError, SourceUnavailableError
from ..logging_utils import get_logger
from ..models import ExtractedDocument, SourceRecord, SourceRequest
from .base import SourceAdapter, sha256_bytes, utc_now, validate_https_url

LOGGER = get_logger("sources.web")

_SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "form", "iframe", "svg"}
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "section", "article", "tr", "table"}
_WHITESPACE_RE = re.compile(r"[ \t\u3000]+")


class _TextExtractor(HTMLParser):
    """去噪文本抽取器：跳过脚本/样式/导航，保留正文与标题。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = _WHITESPACE_RE.sub(" ", data).strip()
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        self._chunks.append(text + " ")

    def text(self) -> str:
        raw = "".join(self._chunks)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def extract_html_text(html: str) -> tuple[str, str]:
    """返回 (标题, 去噪正文)。"""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser 对极端输入的防御
        raise SourceUnavailableError(f"HTML 解析失败: {exc}") from exc
    return parser.title, parser.text()


class HttpsSource(SourceAdapter):
    """允许域名内的网页来源；请求大小与重试受策略控制。"""

    source_type = "https_url"

    def collect(self, request: SourceRequest) -> list[SourceRecord]:
        self.require_network()
        urls = [item.strip() for item in (request.notes or "").split() if item.strip()]
        records: list[SourceRecord] = []
        for url in urls[: request.max_results]:
            validate_https_url(url, self.policy, allowed_domains=request.allowed_domains or None)
            raw = self.fetcher.get(url, accept="text/html")
            try:
                html = raw.decode("utf-8", errors="replace")
            except Exception as exc:  # pragma: no cover - bytes.decode 几乎不失败
                raise SourceUnavailableError(f"页面解码失败: {url}: {exc}") from exc
            title, text = extract_html_text(html)
            if not text.strip():
                raise InputContractError(
                    f"页面无可读正文（可能为动态渲染）: {url}",
                    suggested_action="改用静态页面或提供文本版来源",
                )
            records.append(
                SourceRecord(
                    source_id=f"src-web-{_slug(url)}",
                    source_type="https_url",
                    title=title or url,
                    url=url,
                    accessed_at=utc_now(),
                    sha256=sha256_bytes(text.encode("utf-8")),
                    license_note="公开网页，仅保留去噪正文用于科研分析",
                    verification_status="verified",
                )
            )
        if not records:
            raise SourceUnavailableError("HTTPS 来源未采集到任何页面")
        return records

    def extract_text(self, record: SourceRecord) -> ExtractedDocument:
        """重新抓取登记页面并抽取正文（离线模式不应调用）。"""
        if not record.url:
            raise InputContractError(f"HTTPS 来源缺少 url: {record.source_id}")
        self.require_network()
        validate_https_url(record.url, self.policy)
        raw = self.fetcher.get(record.url, accept="text/html")
        html = raw.decode("utf-8", errors="replace")
        title, text = extract_html_text(html)
        return ExtractedDocument(
            source_id=record.source_id,
            pages=[text],
            page_count=1,
            total_chars=len(text),
            sha256=sha256_bytes(text.encode("utf-8")),
            requires_ocr=False,
            note=f"页面标题: {title}" if title else None,
        )


def _slug(url: str) -> str:
    digest = sha256_bytes(url.encode("utf-8"))[:12]
    host = re.sub(r"[^a-z0-9]+", "-", url.split("//", 1)[-1].split("/", 1)[0]).strip("-")[:32]
    return f"{host}-{digest}"

"""PubMed 来源：NCBI E-utilities ESearch/EFetch（设计文档 01 §11.3）。

- ESearch 按检索词获取 PMID；EFetch 获取标题、作者、年份、摘要、
  期刊与 DOI。
- 请求频率受 ``source_policy.request_interval_seconds`` 控制（经
  :class:`~qwen_harness.sources.base.HttpFetcher` 限流）。
- 保留检索词、返回顺序与访问时间（写入 ``license_note`` 与记录顺序）。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from ..errors import InputContractError, SourceUnavailableError
from ..logging_utils import get_logger
from ..models import ExtractedDocument, SourceRecord, SourceRequest
from .base import SourceAdapter, sha256_bytes, utc_now, validate_https_url

LOGGER = get_logger("sources.pubmed")

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_URL_TEMPLATE = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


class PubMedSource(SourceAdapter):
    """PubMed 元数据采集；``notes`` 传入检索词或指定 PMID。"""

    source_type = "pubmed"

    def collect(self, request: SourceRequest) -> list[SourceRecord]:
        self.require_network()
        pmids: list[str] = []
        terms_used: list[str] = []
        explicit = [item.strip() for item in (request.notes or "").split(",") if item.strip().isdigit()]
        if explicit:
            pmids = explicit[: request.max_results]
        else:
            for term in request.terms:
                found = self._esearch(term, request.max_results)
                if found:
                    terms_used.append(term)
                    for pmid in found:
                        if pmid not in pmids:
                            pmids.append(pmid)
                if len(pmids) >= request.max_results:
                    break
        if not pmids:
            raise SourceUnavailableError(
                "PubMed 检索未返回任何 PMID",
                suggested_action="更换检索词，或改用离线固定来源",
            )
        pmids = pmids[: request.max_results]
        articles = self._efetch(pmids)
        records: list[SourceRecord] = []
        for pmid in pmids:  # 保留检索返回顺序
            article = articles.get(pmid)
            if article is None:
                LOGGER.warning("EFetch 未返回 PMID %s，已跳过", pmid)
                continue
            metadata = json.dumps(article, ensure_ascii=False, sort_keys=True)
            records.append(
                SourceRecord(
                    source_id=f"src-pubmed-{pmid}",
                    source_type="pubmed",
                    title=article["title"],
                    authors=article["authors"],
                    year=article["year"],
                    doi=article["doi"],
                    pmid=pmid,
                    url=PUBMED_URL_TEMPLATE.format(pmid=pmid),
                    accessed_at=utc_now(),
                    sha256=sha256_bytes(metadata.encode("utf-8")),
                    license_note=(
                        "PubMed metadata via NCBI E-utilities; "
                        f"terms={terms_used or 'explicit-pmid'}"
                    ),
                    verification_status="verified" if article["title"] else "partial",
                )
            )
        if not records:
            raise SourceUnavailableError("PubMed EFetch 未返回可用元数据")
        return records

    # -- E-utilities -----------------------------------------------------------
    def _esearch(self, term: str, max_results: int) -> list[str]:
        url = f"{ESEARCH_URL}?db=pubmed&retmode=json&retmax={max_results}&term={_quote(term)}"
        validate_https_url(url, self.policy)
        data = json.loads(self.fetcher.get(url, accept="application/json").decode("utf-8"))
        id_list = data.get("esearchresult", {}).get("idlist", [])
        return [str(item) for item in id_list]

    def _efetch(self, pmids: list[str]) -> dict[str, dict[str, object]]:
        url = f"{EFETCH_URL}?db=pubmed&retmode=xml&id={','.join(pmids)}"
        raw = self.fetcher.get(url, accept="application/xml")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise SourceUnavailableError(f"PubMed EFetch 返回无法解析: {exc}") from exc
        articles: dict[str, dict[str, object]] = {}
        for article in root.iter("PubmedArticle"):
            pmid = self._text(article, ".//PMID")
            if not pmid:
                continue
            title = self._text(article, ".//ArticleTitle") or ""
            year_text = self._text(article, ".//PubDate/Year") or self._text(
                article, ".//PubDate/MedlineDate"
            )
            year = _parse_year(year_text)
            authors: list[str] = []
            for author in article.findall(".//Author"):
                last = self._text(author, "LastName")
                fore = self._text(author, "ForeName")
                if last:
                    authors.append(f"{last} {fore}".strip())
            doi = None
            for article_id in article.findall(".//ArticleId"):
                if article_id.get("IdType") == "doi":
                    doi = (article_id.text or "").strip() or None
            abstract_parts = [
                (part.text or "").strip()
                for part in article.findall(".//AbstractText")
                if (part.text or "").strip()
            ]
            journal = self._text(article, ".//Journal/Title") or ""
            articles[pmid] = {
                "title": title.strip(),
                "authors": authors,
                "year": year,
                "doi": doi,
                "journal": journal,
                "abstract": " ".join(abstract_parts),
            }
        return articles

    @staticmethod
    def _text(node: ET.Element, path: str) -> str | None:
        element = node.find(path)
        if element is None or element.text is None:
            return None
        return element.text.strip()

    def extract_text(self, record: SourceRecord) -> ExtractedDocument:
        """PubMed 来源的可检索文本 = EFetch 元数据与摘要。"""
        if not record.pmid:
            raise InputContractError(f"PubMed 来源缺少 pmid: {record.source_id}")
        articles = self._efetch([record.pmid])
        article = articles.get(record.pmid)
        if article is None:
            raise SourceUnavailableError(f"PubMed 未返回 PMID {record.pmid} 的元数据")
        text = json.dumps(article, ensure_ascii=False, indent=2)
        return ExtractedDocument(
            source_id=record.source_id,
            pages=[text],
            page_count=1,
            total_chars=len(text),
            sha256=sha256_bytes(text.encode("utf-8")),
            requires_ocr=False,
            note="EFetch 元数据与摘要",
        )


def _quote(term: str) -> str:
    from urllib.parse import quote

    return quote(term)


def _parse_year(text: str | None) -> int | None:
    if not text:
        return None
    digits = "".join(ch for ch in text[:4] if ch.isdigit())
    if len(digits) == 4:
        return int(digits)
    return None

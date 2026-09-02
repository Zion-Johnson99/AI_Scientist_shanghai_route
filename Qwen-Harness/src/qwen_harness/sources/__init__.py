"""来源采集与引用核验（设计文档 01 §11）。

对外导出：

- ``source_collection_stage`` —— source_collection 阶段冻结处理器。
- ``CitationGate`` / ``stage_handler`` —— citation_validation 阶段。
- 五类来源适配器：``LocalFileSource``、``PubMedSource``、``CrossrefSource``、
  ``HttpsSource``、``RepositorySource``。
- 策略工具：``HttpFetcher``、``validate_https_url``、``load_fixture_sources``。
"""

from .base import (
    FIXTURE_SOURCES_RELATIVE,
    HttpFetcher,
    SourceAdapter,
    classify_seed,
    fixture_sources_dir,
    load_fixture_sources,
    load_source_manifest,
    source_collection_stage,
    validate_https_url,
)
from .citation_gate import CitationGate
from .citation_gate import stage_handler as citation_validation_stage_handler
from .crossref import CrossrefSource
from .local_files import LocalFileSource
from .pubmed import PubMedSource
from .repository import RepositorySource
from .web import HttpsSource

__all__ = [
    "FIXTURE_SOURCES_RELATIVE",
    "CitationGate",
    "CrossrefSource",
    "HttpFetcher",
    "HttpsSource",
    "LocalFileSource",
    "PubMedSource",
    "RepositorySource",
    "SourceAdapter",
    "citation_validation_stage_handler",
    "classify_seed",
    "fixture_sources_dir",
    "load_fixture_sources",
    "load_source_manifest",
    "source_collection_stage",
    "validate_https_url",
]

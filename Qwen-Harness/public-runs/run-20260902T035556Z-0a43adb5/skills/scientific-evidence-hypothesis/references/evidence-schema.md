# Evidence Schema

所有模型继承 `StrictModel`（`extra="forbid"`）。字段名保留英文。

## SourceRecord

```python
class SourceRecord(StrictModel):
    source_id: str
    source_type: Literal["local_file", "pubmed", "crossref", "https_url", "repository_file"]
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    pmid: str | None
    url: str | None
    local_path: str | None
    accessed_at: datetime
    sha256: str
    license_note: str
    verification_status: Literal["verified", "partial", "unverified", "rejected"]
```

约束：

- `source_id` 全局唯一，稳定可读（建议 `<type>-<序号>` 或 DOI 派生）。
- `sha256` 为内容哈希；`https_url` 类型记录抓取页面正文哈希。
- `local_path` 仅限仓库内或用户显式允许的输入目录。
- 缺作者、年份、DOI/PMID 时置 `null`，不推断。

## EvidenceClaim

```python
class EvidenceClaim(StrictModel):
    claim_id: str
    source_id: str
    claim: str
    evidence_location: str
    short_excerpt: str | None
    evidence_type: Literal["result", "method", "dataset", "limitation", "definition", "policy"]
    support_strength: Literal["high", "medium", "low"]
    caveats: list[str]
```

约束：

- `source_id` 必须已在来源注册表中。
- `evidence_location` 使用页码、章节、摘要字段或模块文件路径。
- `short_excerpt` 仅用于定位，长度受 `source_policy.json` 上限约束；完整报告优先转述。
- 涉及数值的 claim 必须在原文或模块结果中可找到。

## KnowledgeGap

```python
class KnowledgeGap(StrictModel):
    gap_id: str
    statement: str
    supported_by_claim_ids: list[str]
    affected_variables: list[str]
    why_unresolved: str
    available_data: list[str]
    missing_data: list[str]
    testability: Literal["high", "medium", "low"]
    product_relevance: Literal["high", "medium", "low"]
```

## HypothesisCandidate / HypothesisSet

```python
class HypothesisCandidate(StrictModel):
    hypothesis_id: str
    statement: str
    mechanism: str
    independent_variables: list[str]
    dependent_variables: list[str]
    moderators: list[str]
    expected_direction: str
    falsification_criteria: list[str]
    required_data: list[str]
    supporting_claim_ids: list[str]
    novelty_argument: str
    feasibility_score: float
    scientific_value_score: float
    risks: list[str]
```

`HypothesisSet` 含 3 个候选与 `recommended_hypothesis_id`。`supporting_claim_ids` 必须全部可解析。

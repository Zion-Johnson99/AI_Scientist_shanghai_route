# Source Adapters

`SourceAdapter` 协议：

```python
class SourceAdapter(Protocol):
    source_type: str
    def collect(self, request: SourceRequest) -> list[SourceRecord]: ...
    def extract_text(self, source: SourceRecord) -> ExtractedDocument: ...
```

## local_file（LocalFileSource）

- 支持 `.md`、`.txt`、`.json`、可搜索 `.pdf`。
- 路径限定在仓库或用户显式允许的输入目录。
- PDF 用 `pypdf` 按页提取；记录页数、每页字符数和 SHA256。
- 页面无文本时标记 `requires_ocr`，v1 停止该来源并报告（不做 OCR）。

## pubmed（PubMedSource）

- ESearch 获取 PMID；EFetch 获取标题、作者、年份、摘要、期刊、DOI。
- 按 `source_policy` 控制请求频率。
- 保留检索词、返回顺序和访问时间。

## crossref（CrossrefSource）

- 负责 DOI 元数据核验与补充。
- 标题相似度过低、年份冲突或 DOI 格式异常时标记 `partial` 或 `rejected`。

## https_url（HttpsSource）

- 只访问允许域名，仅 HTTPS。
- 用标准库 `HTMLParser` 去除脚本、样式和导航噪声。
- 最大响应大小与超时由配置控制。
- URL 含用户名、密码或片段时拒绝。

## repository_file（RepositorySource）

- 读取仓库 README、配置、数据 Schema 与审计文件。
- 任何代码事实都附文件路径和 SHA256。

## 网络与回退

- 网络来源需显式授权；按 `source_policy.json` 限流与重试。
- 429、504、超时簇或重复失败：停止该来源，保留检索词、参数、缓存状态和错误上下文。

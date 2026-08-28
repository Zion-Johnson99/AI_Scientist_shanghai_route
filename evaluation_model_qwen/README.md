# 徐汇健康路线评价与千问 CLI

本模块从徐汇区 90 条已验收路线中执行硬约束筛选、五维基础评分和千问个性化审核，输出首选路线与备选路线。首版覆盖当前至未来 24 小时，读取兄弟目录中的路线与环境网页数据包。

## 安装

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop\evaluation_model_qwen
uv sync --extra dev
Copy-Item .env.example .env
```

在 `.env` 中填写：

- `DASHSCOPE_API_KEY`：百炼 API Key
- `DASHSCOPE_BASE_URL`：包含 Workspace ID 的北京专属兼容接口
- `QWEN_MODEL`：默认 `qwen3.7-plus`
- `QWEN_TIMEOUT_SECONDS`：默认 30 秒

密钥只保存在本地 `.env`，日志和推荐记录均隐藏密钥。

`DASHSCOPE_BASE_URL` 需将 `<WorkspaceId>` 替换为百炼控制台右上角显示的业务空间 ID。参考[百炼 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)与 [Workspace ID 获取方式](https://help.aliyun.com/zh/model-studio/obtain-the-app-id-and-workspace-id)。

## 使用

验证千问结构化调用：

```powershell
.\.venv\Scripts\evaluation-model-qwen.exe api-check
```

启动交互问卷：

```powershell
.\.venv\Scripts\evaluation-model-qwen.exe recommend
```

复现固定画像：

```powershell
.\.venv\Scripts\evaluation-model-qwen.exe recommend --profile examples/profile_walk.json
```

只运行 Python 基础评分：

```powershell
.\.venv\Scripts\evaluation-model-qwen.exe recommend --profile examples/profile_walk.json --offline
```

追加 `--json` 可向标准输出打印完整结果。每次推荐同时写入 `runtime/recommendations/<run_id>.json`。

`api-check` 成功时返回退出码 0，配置缺失或 API 异常时返回 1。`recommend` 默认调用千问；鉴权、限流、超时、网络或响应校验失败时，结果标记为 `degraded` 并回退到 Python 基础排序。

## 数据边界

- 路线 PM2.5：约 1 km 格网估计，按路线段长度加权。
- 花粉：日级约 1 km 区域估计；全区同值时只生成提醒。
- 噪声：约 100 m 路段的 0–100 风险代理，数值不代表实测分贝。
- 未来 PM2.5：上游当前缺少浓度，系统保留缺值且不从 AQI 推导。
- 接驳距离：推荐阶段使用 GCJ-02 起点直线距离；准确接驳路径仍由现有高德导航处理。

上游数据过期或缺失时，先在数据模块中手动刷新：

```powershell
cd ..\weather_api_data
.\.venv\Scripts\weather-api-data.exe --root . --env-file .env refresh-all
```

推荐 CLI 只读取已发布数据包，运行期不会触发刷新。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pyright.exe --pythonpath .\.venv\Scripts\python.exe
git diff --check
```

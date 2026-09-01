# 徐汇健康路线评价与千问推荐

_从用户需求到可解释路线推荐的评价服务。_

---

## 模块介绍

本模块面向徐汇户外健康地图，从 90 条步行、跑步和骑行路线中选择更符合当前需求的方案。服务使用阿里云百炼千问 `qwen3.7-plus`，结合可复现的本地评分，为用户生成首选路线、备选路线、推荐理由和出行提醒。

推荐链路为：用户画像与自然语言需求 → 安全检查与硬约束 → 五维评分 → 千问评价与推荐 → 本地排序降级 → 结果记录。

| 环节 | 作用 |
| --- | --- |
| **需求整理** | 读取运动方式、距离、区域、时间、健康敏感项和自然语言偏好 |
| **硬约束筛选** | 按运动方式、距离、范围、路线形态和环境风险缩小候选集 |
| **五维评分** | 综合环境健康、运动匹配、到达便利、路线质量和兴趣服务 |
| **千问评价** | 审核前 5 条候选路线，在明确偏好支持下调整次序并生成解释 |
| **稳定降级** | 千问服务异常时自动采用本地 Python 排序，继续返回推荐结果 |
| **结果记录** | 保存本轮输入、评分和决策来源，支持实验复盘与后续迭代 |

![路线助手推荐界面](../docs/images/readme/qwen-recommendation.png)
*图 1：路线助手展示首选路线、备选路线与推荐理由；本地排序与千问评价共用这套界面*

## 快速体验

需要 Python 3.10 或更高版本，并已安装 [uv](https://docs.astral.sh/uv/)。从仓库根目录执行：

```powershell
cd .\evaluation_model_qwen
uv sync
cd ..
```

默认使用本地排序启动完整网站，不消耗千问额度：

```powershell
.\start-local-app.ps1
```

启用千问评价与推荐：

```powershell
.\start-local-app.ps1 -UseQwen
```

启动完成后访问 `http://127.0.0.1:8123/web/`。统一启动还会连接路线网页和环境数据；其余模块的首次配置见仓库根目录 `README.md`。

macOS 或 Linux 使用：

```bash
bash ./start-local-app.sh
bash ./start-local-app.sh --use-qwen
```

## 配置千问（可选）

希望体验千问推荐时，先复制配置模板：

```powershell
cd .\evaluation_model_qwen
Copy-Item .env.example .env
```

在 `.env` 中填写：

| 配置项 | 填写内容 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key |
| `DASHSCOPE_BASE_URL` | 将模板中的 `<WorkspaceId>` 替换为百炼业务空间 ID |
| `QWEN_MODEL` | 默认 `qwen3.7-plus`，通常保留原值 |

真实凭据保存在本地 `.env`，公开仓库只保留空白模板。接口地址与业务空间 ID 可参考[百炼 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)和 [Workspace ID 获取说明](https://help.aliyun.com/zh/model-studio/obtain-the-app-id-and-workspace-id)。

配置完成后可先检查连接：

```powershell
.\.venv\Scripts\evaluation-model-qwen.exe api-check
```

## 单独使用 API 或 CLI

### 启动推荐 API

```powershell
cd .\evaluation_model_qwen
.\.venv\Scripts\evaluation-model-qwen-api.exe --host 127.0.0.1 --port 8124
```

服务入口：

- `GET /api/v1/health`：查看服务、路线数据和千问配置状态
- `GET /api/v1/questionnaire`：读取网页问卷选项
- `POST /api/v1/recommendation-intent`：将自然语言整理为结构化偏好
- `POST /api/v1/recommendations`：生成路线推荐结果

### 使用命令行推荐

```powershell
# 交互填写需求并调用千问
.\.venv\Scripts\evaluation-model-qwen.exe recommend

# 使用示例画像复现一轮推荐
.\.venv\Scripts\evaluation-model-qwen.exe recommend --profile examples/profile_walk.json

# 仅运行本地筛选与评分
.\.venv\Scripts\evaluation-model-qwen.exe recommend --profile examples/profile_walk.json --offline
```

每次推荐都会保留一份本地结果记录，用于比较不同需求、环境数据和模型判断下的实验结果。

## 验证

先安装开发验证工具：

```powershell
uv sync --extra dev
```

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pyright.exe --pythonpath .\.venv\Scripts\python.exe
```

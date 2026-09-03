# 复现说明

## 环境

- Python 3.11（3.10 起可用）
- Node.js 20+（本次运行使用 v24）
- 无需任何第三方 Python 包；标准库即可
- 无需任何 API 密钥

## 顺序

```powershell
cd workspace/source

# 1. 抓取公开原始数据（需要外网；已有 sources/ 时可跳过）
python ../../commands/fetch_osm4_api.py
python -m environment.fetch_public

# 2. 生成 90 条路线与全部路线产物
python reproduce.py --stage routes

# 3. 生成 54 格环境网格与路线暴露
python reproduce.py --stage environment

# 4. 打分、推荐、基线与实验矩阵
python reproduce.py --stage evaluation

# 5. 组装网页载荷与本地成品
python reproduce.py --stage web

# 6. 全部质量门禁与 checks/ 产物
python reproduce.py --stage checks
```

一次性执行：`python reproduce.py --stage all`。

## 确定性

- 不使用 `random`、不使用系统时钟参与计算。
- 所有时间戳由入口脚本一次性生成并作为参数向下传递。
- 相同 `sources/` 输入产生逐字节相同的产物（浮点统一 `round` 到固定位数）。

## 离线约束

复现全过程不得初始化任何大模型客户端，不得读取 `.env`。
`reproduce.py` 会在启动时断言 `DASHSCOPE_API_KEY` 与 `OPENAI_API_KEY`
未进入子进程环境，若存在则以清除后的环境重启自身。

## 验证

```powershell
cd workspace/source
uv run pytest Qwen-Harness/tests weather_api_data/tests evaluation_model_qwen/tests xuhui_route_builder/tests tests
uv run ruff check .
uv run pyright
cd node
node --test
```

## 本地网页

```powershell
pwsh ../../publish/launch-local.ps1
```

脚本在 `publish/local-product` 下启动 `python -m http.server`，
默认端口 8765，打印访问地址并保持前台运行。

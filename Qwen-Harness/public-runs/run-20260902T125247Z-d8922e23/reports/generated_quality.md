# 工程质量门禁结果

- source_root: `workspace/source`
- 总体结论: passed
- required 检查数: 14
- 通过数: 14

| 检查 | 类别 | 状态 | 退出码 | 耗时(s) | 日志 |
| --- | --- | --- | --- | --- | --- |
| pytest:Qwen-Harness | pytest | passed | 0 | 1.0 | `commands/quality/pytest_Qwen-Harness.out` |
| pytest:evaluation_model_qwen | pytest | passed | 0 | 1.0 | `commands/quality/pytest_evaluation_model_qwen.out` |
| pytest:weather_api_data | pytest | passed | 0 | 0.8 | `commands/quality/pytest_weather_api_data.out` |
| ruff:Qwen-Harness | ruff | passed | 0 | 0.1 | `commands/quality/ruff_Qwen-Harness.out` |
| pyright:Qwen-Harness | pyright | passed | 0 | 2.7 | `commands/quality/pyright_Qwen-Harness.out` |
| ruff:xuhui_route_builder | ruff | passed | 0 | 0.1 | `commands/quality/ruff_xuhui_route_builder.out` |
| pyright:xuhui_route_builder | pyright | passed | 0 | 2.8 | `commands/quality/pyright_xuhui_route_builder.out` |
| ruff:weather_api_data | ruff | passed | 0 | 0.1 | `commands/quality/ruff_weather_api_data.out` |
| pyright:weather_api_data | pyright | passed | 0 | 2.9 | `commands/quality/pyright_weather_api_data.out` |
| ruff:evaluation_model_qwen | ruff | passed | 0 | 0.1 | `commands/quality/ruff_evaluation_model_qwen.out` |
| pyright:evaluation_model_qwen | pyright | passed | 0 | 2.8 | `commands/quality/pyright_evaluation_model_qwen.out` |
| Node 契约测试 | node | passed | 0 | 0.9 | `commands/quality/Node_契约测试.out` |
| 评价 API 健康检查 | evaluation_api | passed | 0 | 1.0 | `commands/quality/评价_API_健康检查.out` |
| 真实浏览器验收 | browser | passed | 0 | 1.1 | `commands/quality/真实浏览器验收.out` |

失败检查的 stderr 摘要：

无。
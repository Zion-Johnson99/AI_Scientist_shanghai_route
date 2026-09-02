"""报告与网页数据产物（设计文档 01 §19）。

- ``scientific_plan``：组装并落盘 ``reports/scientific_plan.json``
  （``models.ScientificPlan`` 契约，覆盖赛题字段）。
- ``markdown``：生成 ``reports/scientific_plan.md``、
  ``reports/experiment_report.md``、``reports/reproducibility.md``。
- ``web_payload``：``web_payload`` 阶段处理器，组装脱敏后的
  ``publish/research_harness_latest.json``（``models.WebPayload`` 契约），
  由轮 1 的 ``publish_web_stage`` 原子复制到网页数据目录。

报告的科学边界（进入 limitations 与网页 payload）：PM2.5 为网格/站点融合
估计；花粉为日级背景/代理；噪声为 0-100 风险代理；不声明问卷、盲评、
传感器或实测证据。
"""

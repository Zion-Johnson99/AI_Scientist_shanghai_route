# Experiment Matrix

## 预设画像（`profiles.py`）

从现有问卷字段生成固定案例矩阵，至少覆盖：

- `walk`、`run`、`bike`。
- `balanced`、`health_environment`、`nearby`、`scenery`。
- 空气、花粉、噪声敏感。
- 滨水、公园、安静、厕所、便利设施偏好。
- 无出发点的全徐汇筛选与有出发点的接驳筛选。

每个案例有唯一 `case_id`。目标时段使用快照时间附近的固定时刻，避免“现在”导致不可复现。预设画像案例不解释为独立人群样本，不外推临床或人群结论。

## 基线与模型

| ID | 规则 |
| --- | --- |
| `B0_shortest_feasible` | 在可行候选中最小化目标距离偏差与接驳距离 |
| `B1_pm25_only` | 在距离门禁内最小化 PM2.5 |
| `B2_multi_environment` | 综合 PM2.5、噪声和花粉，忽略个人兴趣 |
| `B3_non_personalized` | 使用默认平衡权重，不提升敏感项与兴趣项 |
| `M1_personalized_constrained` | 使用用户目标、敏感项、兴趣、接驳和数据可信度，受附加距离门禁约束 |

基线规则由 Harness 预注册，模型无法临时改动。这些变体仅用于验证核心假设所需的最小基线对比；v1 不扩展为系统性消融实验，也不引入多时段环境快照实验。

## 原始指标

PM2.5 数值与健康分、噪声代理值、花粉风险、环境数据可靠度、目标距离偏差、接驳距离、偏好命中率、五维得分、约束通过率、无候选率。

## 派生指标

- 偏好命中率：$F_{\mathrm{pref}}=|I_{\mathrm{requested}} \cap I_{\mathrm{matched}}| / \max(1,|I_{\mathrm{requested}}|)$。
- 综合暴露风险（预注册归一化，不从综合效用反推）：$R_{\mathrm{env}}=\alpha R_{\mathrm{PM2.5}}+\beta R_{\mathrm{noise}}+\gamma R_{\mathrm{pollen}}$，系数来自实验变体配置并在运行前冻结。
- 个性化增益：$\Delta F_{\mathrm{pref}}=F_{\mathrm{pref}}^{M1}-F_{\mathrm{pref}}^{B0}$。
- 环境风险改善：$\Delta R_{\mathrm{env}}=R_{\mathrm{env}}^{B0}-R_{\mathrm{env}}^{M1}$。

## 统计摘要（`statistics.py`）

只用标准库，固定 seed 1234。输出：中位数、四分位距、胜率、约束通过率、配对差值、配对 bootstrap 95% 区间。

## 支持状态门禁（`quality_gates.json` 预注册）

```json
{
  "supported": {
    "detour_pass_rate_min": 0.90,
    "environment_win_rate_min": 0.60,
    "preference_win_rate_min": 0.60,
    "reference_verification_rate_min": 1.0,
    "fatal_data_errors_max": 0
  }
}
```

状态：`supported`、`partially_supported`、`unsupported`、`inconclusive`。任何运行时调整进入迭代记录。

## 距离约束

- 同端点附加距离：$\rho_{\mathrm{detour}}=(d_{\mathrm{candidate}}-d_{\mathrm{shortest}})/d_{\mathrm{shortest}} \le 0.20$。
- 运动路线目标距离偏差：$\rho_{\mathrm{target}}=|d_{\mathrm{route}}-d_{\mathrm{target}}|/d_{\mathrm{target}} \le 0.15$。
- 接驳距离服从用户搜索半径与现有硬约束。

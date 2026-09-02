# Benchmark v2 Train Baseline 执行预案

## 目标与数据边界

本轮只收集固定 ReAct Policy 在 Benchmark v2 Train 上的初始失败证据，为后续 Reflection、
Experience 与 Policy Evolution 提供输入。它不是最终性能评测，也不用于比较演化前后的收益。

- Train：task_101–108，允许本轮运行并用于后续失败分析；
- Validation：task_109–113，本轮禁止访问，只在候选策略 Gate 中使用；
- Test：task_114–118，本轮禁止访问，只用于冻结后的最终盲测。

只运行 Train 可以避免根据 Validation/Test 结果修改 Agent、Policy 或 Experience，维持后续结论
的数据隔离。正式 Benchmark Manifest Hash 固定为
`c5ad46d8963400db6f31eeee64a0abe5029eeb1a4cee8e308af6a3e5f6c92ee6`。

## 冻结运行矩阵

| 项目 | 固定值 |
|---|---|
| Task | task_101–108，共 8 题 |
| Repetition | 每题 2 次 |
| 预期 Agent Run | 16 |
| Provider / Model | DeepSeek / `deepseek-v4-flash` |
| Temperature | 0.1 |
| Policy | `fixed-react-v1` |
| Max ReAct Steps | 15 |
| Context Budget | 60,000 字符 |
| Experience | Disabled |
| 选择性补跑 | 禁止；所有有效失败均保留 |

机器可读合同位于
[`configs/experiments/benchmark-v2-train-baseline-v1.yaml`](../configs/experiments/benchmark-v2-train-baseline-v1.yaml)。

## 离线预检与付费门禁

以下命令只解析配置、验证 Manifest 并输出 16 个确定性 Run ID，不需要 Docker 或 API 调用：

```powershell
evodev-baseline --project-root . --benchmark-root benchmarks-v2 `
  --experiment-id exp-baseline-v2-train-v1 --repetitions 2 --split train --plan
```

真实运行必须显式增加 `--confirm-paid`。该参数只是程序级防误触门禁，不代替用户授权；没有单独
收到本轮付费授权时，不执行 Agent。获得授权后还应先确认 Git Commit、Benchmark Hash、Docker
Image Digest、Tool Catalog Hash、模型配置和 16 个 Run ID，再启动正式运行。

## Token 与费用预算

历史 V2 Pilot 的 8 次调用共使用 589,813 input tokens 和 61,812 output tokens。按调用数线性
外推，16 次 Baseline 约为 1,179,626 input tokens 和 123,624 output tokens。

价格于 2026-09-02 从 [DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)
核对。按 `deepseek-v4-flash` cache-miss 计价，估算如下：

| 场景 | 估算费用 |
|---|---:|
| 低峰，历史 Token 线性外推 | 0.3411 USD |
| 峰值，历史 Token 线性外推 | 0.6822 USD |
| 峰值，Token 再翻倍 | 1.3644 USD |
| 单轮授权上限 | 2.00 USD |

费用只是预算，不是账单保证。供应商价格、缓存命中、实际上下文长度和重试都会影响账单；正式执行
前必须重新核对官方价格，实际记录以供应商报告的用量为准。若预计超过 2.00 USD，应停止并重新
申请授权。

## 完成判据与执行结果

正式运行完成后应冻结 Experiment Manifest、16 份 Trajectory、独立评测结果与汇总，并验证每个
预定 Run ID 恰好出现一次。Agent 错误与失败结果同样进入汇总，不因结果不理想而补跑。

该预案于 2026-09-02 获得单独付费授权后完整执行：16/16 个预定 Run ID 均产生有效独立评测，
没有选择性补跑。结果为 6/16 Resolved（37.5%）；task_101、102、104 均为 2/2，其余五题均为
0/2。实际记录 2,289,513 input tokens 与 225,762 output tokens；按峰值且全部 input cache miss
保守估算为 1.3054 USD，低于 2.00 USD 上限，实际账单以供应商为准。

公开冻结结果位于
[`experiments/benchmark-v2-train-baseline-v1`](../experiments/benchmark-v2-train-baseline-v1/README.md)。
该结果只建立 Train Baseline 与失败证据，不能解释为演化收益，也不提供 Validation/Test 成绩。

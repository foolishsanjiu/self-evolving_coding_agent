# Benchmark v2 Experience Validation Preflight

本目录冻结 `experience-v002` 在正式 Benchmark v2 Validation 公共元数据上的离线检索审计。
本轮没有调用模型、没有启动 Docker，也没有读取 hidden tests、Gold Patch 或 Test split。

## 审计结果

| Validation Task | Category | Retrieval Hit | Selected Experience | Prompt Chars |
|---|---|:---:|---|---:|
| task_109 | cross_module_bug | No | — | 0 |
| task_110 | state_data_flow | No | — | 0 |
| task_111 | feature | No | — | 0 |
| task_112 | error_resilience | No | — | 0 |
| task_113 | test_repair_compatibility | Yes | `exp_ea8b...4772d` | 992 |

覆盖率为 **1/5（20%）**，只选择了 7 条 active Experience 中的一条。其余四题的 Relevant
Prompt 与 Baseline 完全相同，因此现在执行 5 题 × 2 repetitions × 2 arms 的 20 次付费调用，
实际上只有 task_113 具备可观测的处理差异，难以形成有说服力的 Experience 整体结论。

## 决策

本预检状态为 `blocked_before_paid_execution`：暂不运行 Baseline/Relevant Validation。该结论
不是因为效果失败，而是处理覆盖不足；当前没有产生 Validation 成绩。

下一步只能使用 Train 来源修复检索元数据契约，例如保证每条 Experience 带有可信的源任务
category，并以 Train leave-one-task-out 覆盖率验证。不能根据本次 Validation 的具体题意定制
关键词或经验，否则会把 Gate 变成训练集。完成 Train-only 修复并冻结新快照后，只允许再执行
一次相同的公共元数据预检，随后锁定检索器再进入付费实验。

## 未来对照设计

若解除阻断，预案为 5 道 Validation、每题 2 次、Baseline/Relevant 各 10 次，总计 20 次；
禁止选择性补跑。按 V2 Train Baseline 的平均 token 线性外推，峰值全 cache-miss 约 1.6317 USD，
建议授权上限 2.00 USD。该预算必须在执行前重新核对官方价格并重新获得用户授权。

机器可读审计见 [retrieval-audit.json](retrieval-audit.json)，完整合同见
[`benchmark-v2-experience-validation-v1.yaml`](../../configs/experiments/benchmark-v2-experience-validation-v1.yaml)。

后续状态：Train-only 元数据契约已在
[`benchmark-v2-experience-metadata-v1`](../benchmark-v2-experience-metadata-v1/README.md) 修复并冻结为
`experience-v003`。本目录对 v002 的 1/5 结果保持不变；尚未用 v003 重新读取 Validation。

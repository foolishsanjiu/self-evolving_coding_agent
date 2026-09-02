# Benchmark v2 Experience v004/v005 Runtime Guardrail Holdout

本实验是针对 v005 Runtime Guardrails 的 **Train-only 定向机制测试**。冻结的 Train
leave-one-task-out 审计中，只有 `task_101` 能够检索到来自其他任务的 Experience，因此预先
只选择该题。该实验不访问 Validation/Test，也不声称覆盖完整 Benchmark。

## 冻结设计

| 项目 | v004 control | v005 guardrail |
|---|---|---|
| Snapshot | `experience-v004` | `experience-v005` |
| Consumer | `execution-contract-v1` | `execution-contract-v2` |
| Runtime guardrails | 关闭 | Patch 失败后重读；末次编辑后测试；保留验证窗口 |
| Task / repetitions | `task_101` × 2 | `task_101` × 2 |

两臂均重新运行，固定使用 `deepseek-v4-flash`、temperature 0.1、`fixed-react-v1`、15 Steps、
60,000 字符上下文、相同 Docker 镜像和独立评估器。除 Snapshot、Consumer 与由 v005 合同启用的
Runtime Guardrails 外，其他执行条件必须相同。总计 4 次付费 Agent 调用，禁止选择性补跑。

按前一轮 v004 实测用量和 2026-09-02 官方价格外推，全部输入视为缓存未命中时，淡时约
0.1116 美元、峰时约 0.2231 美元，授权硬上限为 0.50 美元。

Agent 只接收公开题面、仓库与公开测试；Gold Patch 和 hidden tests 不进入 Agent 上下文，
hidden tests 只由运行后的独立评估器使用。机器预检见 [preflight.json](preflight.json)，完整
执行契约见
[`benchmark-v2-experience-guardrails-paid-v1.yaml`](../../configs/experiments/benchmark-v2-experience-guardrails-paid-v1.yaml)。

## 结果

付费前协议已在 Git 提交 `3ffe514` 冻结，随后严格执行 v004、v005 各 2 次调用；4 次调用均
进入独立评测，没有选择性补跑。

| 指标 | v004 | v005 | v005 - v004 |
|---|---:|---:|---:|
| Accepted | 1 / 2 | 2 / 2 | +1 |
| Patch attempts | 14 | 11 | -3 |
| `PATCH_APPLY_FAILED` | 10 | 4 | -6 |
| 未重读 Patch 尝试 | 9 | 2 | -7 |
| 其中被 Runtime Guard 阻断 | 0 | 2 | +2 |
| 实际执行的未重读 Patch | 9 | 0 | -9 |
| Test executions | 2 | 5 | +3 |
| 末次成功编辑已验证 | 2 / 2 | 2 / 2 | 0 |
| 合同遵循 | 2 / 2 | 2 / 2 | 0 |
| Experience 增量利用 | 0 / 2 | 0 / 2 | 0 |
| 平均 Tokens | 105,985.5 | 151,221.0 | +42.68% |
| 平均 Tool Calls | 18.0 | 24.0 | +33.33% |
| 平均延迟 | 65.8 s | 74.5 s | +13.29% |

v005 两条轨迹各发生一次“Patch 失败后未重读就再次 Patch”的尝试，运行时均以
`CONTRACT_PRECONDITION_NOT_MET` 在补丁执行前阻断，随后 Agent 重新读取并恢复；因此门禁机制
的真实模型路径已经得到验证。v005 r01 还发生 2 次验证窗口阻断，将最后步骤保留给测试；四次
合同阻断都由 Agent 正常恢复。v004 的同类 9 次 Patch 尝试全部实际执行。v005 两次均 Accepted，
v004 为一次 Accepted；配对中只有 r01 不一致，exact McNemar 双侧 p=1.0。

实际总用量为 475,556 Input Tokens、38,857 Output Tokens。按执行时淡时费率并将全部输入视为
缓存未命中，保守估算 0.1303 美元，低于 0.50 美元授权上限。

## 结论与停止点

本轮接受“v005 Runtime Guardrails 在真实模型轨迹中能够阻断目标违规”的机制结论：两次目标
违规尝试均被阻断，实际执行的违规从 v004 的 9 次降为 0 次。不能接受“v005 已证明提升成功率”
的性能结论：只有一题、两次重复和一个不一致配对，p=1.0；而且两臂的末次编辑验证与合同遵循
本来都是 2/2，Experience 增量利用也仍为 0/2。v005 同时付出更多 Tokens、Tool Calls 和延迟，
效率没有改善。

机器比较见 [comparison.json](comparison.json)，逐 run 门禁归因见
[guardrail-behavior.json](guardrail-behavior.json)，原始本地证据 Hash 见
[evidence-manifest.json](evidence-manifest.json)。完整轨迹、Agent Patch 和隐藏评估输出仍只保存
在本地 Git ignored 目录。本实验到此停止，不根据该小样本补跑或继续调参。

实验结束后的离线代码审计将 Patch 恢复状态绑定到失败 Diff 的目标路径，并把 Trace Analyzer
指标拆分为违规尝试、运行时阻断与实际执行；归档轨迹重算仍为 v004 实际违规 9 次、v005 0 次。
该兼容加固没有调用模型、没有补跑，也不改变本实验的成功率、成本或统计结论。

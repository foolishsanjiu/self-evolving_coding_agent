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

## 当前停止点

实验协议已冻结并获得用户付费授权，尚未开始模型调用。结果将比较 Accepted、Patch 失败、
失败后未重读重试、末次编辑验证、合同遵循、Tokens、延迟与保守成本；不会根据中间结果改参
或补跑。

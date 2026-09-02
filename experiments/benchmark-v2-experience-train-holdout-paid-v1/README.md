# Benchmark v2 Experience v003/v004 Train Holdout

本实验是针对 Experience 消费机制的 **Train-only 定向机制测试**。它不复用已经结束的 Validation
Gate，也不声称覆盖完整 Benchmark。冻结的 Train leave-one-task-out 审计中，只有 `task_101`
能够检索到来自其他任务（`task_106`）的相关 Experience，因此预先只选择该题；另外七题两臂都
没有 Experience 注入，不能回答执行合同是否有效。

## 冻结设计

| 项目 | v003 arm | v004 arm |
|---|---|---|
| Snapshot | `experience-v003` | `experience-v004` |
| Consumer | `legacy-v1` | `execution-contract-v1` |
| Task | `task_101` | `task_101` |
| Repetitions | 2 | 2 |
| Experience source exclusion | 同任务来源排除 | 同任务来源排除 |

两臂固定使用 `deepseek-v4-flash`、temperature 0.1、`fixed-react-v1`、15 Steps、60,000
字符上下文、相同 Docker 镜像和独立评估器。总计 4 次付费 Agent 调用，禁止选择性补跑。
v004 必须等待 v003 完整结束并将其 Manifest 作为受控对照，只有 Experience Snapshot 与 Consumer
允许变化。

按冻结的 task_101 基线 Token 用量和官方当前价格估算，全部输入视为缓存未命中时，淡时约
0.0644 美元、峰时约 0.1288 美元，授权上限为 0.50 美元。

Agent 只接收公开题面、仓库与公开测试；Validation/Test、Gold Patch 和 hidden tests 不进入
Agent 上下文。hidden tests 只由运行后的独立评估器使用。

机器预检见 [preflight.json](preflight.json)，完整执行契约见
[`benchmark-v2-experience-train-holdout-paid-v1.yaml`](../../configs/experiments/benchmark-v2-experience-train-holdout-paid-v1.yaml)。

## 当前停止点

状态为 `ready_for_paid_execution`。本目录必须先作为 Git 预检提交冻结，随后才可执行已授权的
2 次 v003 与 2 次 v004 调用。结果只用于判断 v004 是否提高合同遵循、增量利用或 task_101
配对成功率；两次重复不足以支持统计显著性或完整 Train 性能结论。

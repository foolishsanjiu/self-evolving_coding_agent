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

## 结果

预检已在 Git 提交 `280afbd` 冻结，随后严格执行 2 次 v003 与 2 次 v004 调用，没有选择性补跑。

| 指标 | v003 | v004 | v004 - v003 |
|---|---:|---:|---:|
| Accepted | 1 / 2 | 1 / 2 | 0 |
| 同一套 v004 合同遵循 | 2 / 2 | 1 / 2 | -1 |
| Experience 增量利用 | — | 0 / 2 | 0 |
| 平均 Tokens | 143,138.5 | 108,923.5 | -34,215.0 |
| 平均 Tool Calls | 26.0 | 22.0 | -4.0 |
| 平均延迟 | 97.1 s | 70.2 s | -26.9 s |

两个配对结果完全反转：r01 为 v004 Accepted、v003 失败，r02 为 v003 Accepted、v004 失败，
exact McNemar 双侧 p=1.0。v004 r01 虽然最终 Accepted，但 `test_runs=0`，没有遵循任一选中
合同；r02 遵循合同但因 Syntax Error 未通过。这再次说明 Accepted、合同遵循和增量利用不能
互相替代。

实际总用量为 460,311 Input Tokens、43,813 Output Tokens。按执行时淡时费率并将全部输入视为
缓存未命中，保守估算 0.1302 美元，低于 0.50 美元授权上限。

## 结论与停止点

本轮不接受 v004 提升成功率、合同遵循率或 Experience 利用率的假设。v004 的 Tokens、Tool Calls
与延迟较低，但单题两次重复只能作为描述性效率信号，不能证明因果改善。结果不用于修改
Validation/Test，也不根据本结果补跑。

机器比较见 [comparison.json](comparison.json)，逐 run 公共行为见
[behavior-comparison.json](behavior-comparison.json)，原始本地证据 Hash 见
[evidence-manifest.json](evidence-manifest.json)。完整轨迹、Agent Patch 和隐藏评估输出仍只保存在
本地 Git ignored 目录。

后续离线归因已将重复 Patch 失败与验证预算耗尽固化为 v005 运行时门禁；该阶段没有付费调用，
也没有改写本目录结果，见
[`benchmark-v2-experience-guardrails-v1`](../benchmark-v2-experience-guardrails-v1/README.md)。

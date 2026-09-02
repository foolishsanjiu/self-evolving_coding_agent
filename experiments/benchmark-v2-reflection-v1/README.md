# Benchmark v2 Train Reflection

本目录冻结正式 Benchmark v2 Train Baseline 失败的结构化 Reflection 与 Experience
提取结果。输入只有 `exp-baseline-v2-train-v1` 的 Train 失败证据；Validation/Test 未访问，
Docker 未参与本阶段。

## 调用与校验结果

| 项目 | 数量 |
|---|---:|
| 已授权 / 实际付费调用 | 9 / 9 |
| 通过本地安全校验 | 8 |
| 被本地安全校验拒绝 | 1 |
| 重试 | 0 |
| 激活 Experience | 7 |
| Provenance Sources | 8 |

首个 `run_task_103_r01` 调用返回的候选复制了 evaluator-specific literals，因而被拒绝；
没有为了凑数放宽校验，也没有补跑。随后软件先修复了“单条拒绝导致整批中止且不记账”的审计
缺陷，再对其余 8 个尚未处理的 Run 各调用一次，全部通过。

后 8 次已保留的调用共使用 18,956 input tokens 与 28,806 output tokens。按 2026-09-02
DeepSeek 公布费率、全部 input cache miss 估算，峰值约 0.0464 USD、低谷约 0.0232 USD。
首个拒绝调用的 token usage 未被旧 runner 持久化，供应商账单也未提交，因此不能把上述数值
表述为九次调用的精确总费用。

## 经验整理

8 个合格 Reflection 产生 8 个候选。其中 task_107 的两次独立失败都指向相同的 injected
executor 生命周期契约，人工审计后合并为一条 Experience 并保留两个来源；最终冻结 7 条
active Experience。它们覆盖：严格布尔解析、无序分片完成条件、兼容旧错误合同、订阅计费、
Patch 失败后的预算恢复、注入 executor 生命周期，以及 callable signature 校验。

冻结快照为 [`experience-v002`](../../experiences/experience-v002.json)，Canonical Hash 为
`8eb3a05d7a1c7aa655688b74f050951234fb2133dc8183b1c2566c05aa1ae5dd`。快照只包含相对
Provenance 路径，不暴露本机目录；完整合格 Reflection 位于 [reflections.json](reflections.json)。

## 结论边界

本阶段证明了 Train failure → bounded evidence → structured Reflection → curated Experience →
immutable snapshot 的链路可运行且可审计。它尚未证明 `experience-v002` 能提升解决率。后续
[Validation 离线预检](../benchmark-v2-experience-validation-plan-v1/README.md)只得到 1/5 检索命中，
因此付费对照在 API 前被阻断；需先以 Train-only evidence 修复检索元数据契约。任何新模型调用
仍需单独付费授权。

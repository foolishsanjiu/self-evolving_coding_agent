# Benchmark v2 Train-only Experience Consumption Contract

本目录冻结 `experience-v003` 到 `experience-v004` 的 Train-only 消费机制升级。该阶段针对正式
Validation 对照暴露出的通用“检索成功但行为不可测”问题，但合同内容只由已有 Train Experience
的 trigger、recommendation 和 rationale 重构而来；没有读取 Validation/Test 题目、hidden tests
或 Gold Patch，也没有模型调用和 Docker 执行。

## 设计

v004 为 7 条 active Experience 分别增加结构化执行合同：

```text
Trigger -> Inspect before editing -> Act -> Verify before finishing
                                      |
                                      +-> public trace targets
```

合同不是新的答案或 Patch，而是把自然语言建议拆成 Agent 可以执行的检查、动作和验证步骤。
每条合同同时绑定现有 `TraceAnalyzer` 的公共特征与 `eq/gte/lte` 运算，例如编辑前检查测试、
读取足够上下文、至少运行一次测试。7/7 Experience 都有完整合同，共 16 个行为目标：

| Trace Feature | Target Count |
|---|---:|
| `inspected_tests_before_edit` | 7 |
| `test_runs` | 7 |
| `unique_files_read` | 2 |

## 版本隔离

历史 `src/evodev/experience/retrieval.py` 保持字节语义不变，规范化 SHA-256 仍为
`bb1f50b47462d0d5f8f5af84dc9efd3332d3e493902b79dc72ab128d182499d2`。新的
`ContractExperienceRetriever` 位于独立模块，只有快照包含执行合同时才启用；v001–v003 继续
走 `legacy-v1`。Preflight、Experiment Manifest 和 Run Metadata 会显式记录 consumer 版本。

## 指标语义

- **Measurable**：至少一条选中 Experience 有完整的公共轨迹目标；
- **Adherent**：Treatment 满足至少一条选中 Experience 的全部目标；
- **Utilized**：Treatment 达成合同，而同 run ID 的 Baseline 未达成。

这样可以区分“文本被注入”“Agent 做到了合同要求”和“Experience 相对 Baseline 产生了新增
行为”，避免把 Retrieval Hit 直接当成 Utilization。

## Train-only 审计

leave-one-task-out 覆盖仍为 1/8，没有通过扩大关键词制造虚假改善。唯一具备跨任务同类经验的
task_101 选择来自 task_106 的两条合同，Prompt 为 1,177 字符，低于 2,500 上限。库存 7/7
合同可被 Schema 验证，所用目标全部属于现有五项公共 Trace Feature。

v004 Canonical Hash 为
`f71ac3984674ba98e52ae02fd939dbc5bf2d4ad998a7013b547ff756f6054988`。确定性合同配置见
[`experience-v004-contracts.yaml`](../../configs/experience-v004-contracts.yaml)，快照见
[`experience-v004.json`](../../experiences/experience-v004.json)，机器审计见
[contract-audit.json](contract-audit.json) 和
[train-retrieval-audit.json](train-retrieval-audit.json)。

## 结论与停止点

本阶段证明消费合同可执行、可版本化、可测量且不破坏历史 Retriever，但没有证明 v004 改善
成功率。后续已经独立冻结并执行单题 v003/v004 Train holdout 对照，结果仍未证明成功率、合同
遵循或增量利用改善，见
[`benchmark-v2-experience-train-holdout-paid-v1`](../benchmark-v2-experience-train-holdout-paid-v1/README.md)。
该结果没有复用或继续调整已完成的 Validation Gate。

# Benchmark V2：评测设计、实验结果与结论边界

本文承接 README 中下沉的 Benchmark V2 研究过程。它记录已经完成并冻结的实验，不修改历史结果，也不把局部机制变化解释为尚未被数据支持的性能提升。

## 结论摘要

Benchmark V2 将受控 Python 修复集扩展到 18 个任务，按 8 Train / 5 Validation / 5 Test 划分。最终样本外实验比较固定 Baseline 与 `Experience + Runtime Contract` Candidate：两臂各执行 10 次，均为 **3/10 Resolved（30%）**；10 个逐 Run 配对中两臂各胜 2 次、平 6 次，双侧 exact McNemar `p=1.0`。因此，V2 没有提供 Candidate 成功率优于 Baseline 的证据。

V2 的正向工程发现来自 Failure Analysis。Agent 在 Patch 失败后会在没有重新读取目标文件的情况下继续尝试修改，也可能在步数即将耗尽时继续编辑而没有留下测试机会。项目将这些软建议下沉为 Runtime Guardrail；在预先冻结的 Train-only 定向实验中，实际执行的“Patch 失败后未重读目标文件就继续 Patch”由 **9 次降为 0 次**。这证明 Guardrail 的阻断路径有效，但单题、每臂两次的样本不足以证明总体成功率提升，且 Guardrail 组的 Token、Tool Calls 和延迟均更高。

## 数据与评测边界

| 项目 | 冻结设计 |
|---|---|
| Benchmark | V2.0，18 个任务 |
| Split | 8 Train / 5 Validation / 5 Test |
| Agent 可见 | 公开任务描述、仓库、公开测试与 Tool Observation |
| Agent 不可见 | Task YAML、Gold Patch、Hidden Target Tests、Hidden Regression Tests |
| Experience 来源 | 仅合格的 Train 失败 |
| Validation 用途 | 候选验证，不写入 Experience |
| Test 用途 | 一次性样本外终局评测，结果产生后关闭 |
| 成功标准 | Fresh Workspace 中 Patch、Syntax、Hidden Target 与 Hidden Regression 全部通过 |

Benchmark 在正式实验前完成 Before-Fail、After-Gold-Pass、Gold 退化、类别配额、Template 跨 Split 和 Manifest Hash 检查。Agent 的自然语言回答、自测结论和原 Agent Workspace 不作为成功证据；失败 Run 也进入预注册分母，不能为了提高分数而选择性补跑。

## 实验阶段

### 1. Pilot 难度校准

正式 V2 前先构建 4 题 Pilot，并对两种固定策略各运行一次，共 8 次调用。总体为 3/8 Accepted，且没有题目被两种策略同时解决。Pilot 只用于确认任务能区分行为和暴露失败模式，不作为正式策略优劣结论。

证据：[Pilot 结果](../experiments/benchmark-v2-pilot-v1/README.md) · [正式任务蓝图](BENCHMARK_V2_BLUEPRINT.md)

### 2. Train Baseline 与失败证据

固定 Baseline 对 8 个 Train 任务各运行 2 次，共 16 次；16/16 均进入独立评测，没有选择性补跑。结果为 **6/16 Resolved（37.5%）**：3 个任务稳定为 2/2，另外 5 个任务稳定为 0/2。后者为 Reflection 提供了持续失败样本，但该结果只是 Train 起点，不是演化收益或最终测试结论。

证据：[Train Baseline](../experiments/benchmark-v2-train-baseline-v1/README.md) · [Failure Evidence](../evolution/benchmark-v2/README.md)

### 3. Reflection 与 Experience 冻结

9 个 eligible Train 失败各执行一次结构化 Reflection 调用。8 条通过本地安全校验，1 条因复制 evaluator-specific literals 被拒绝且未重试；8 个合格 Candidate 去重后冻结为 7 条 active Experience。该阶段证明了 `Train failure → bounded evidence → structured reflection → immutable snapshot` 可以运行和审计，不代表 Experience 已经提高成功率。

证据：[Reflection 结果](../experiments/benchmark-v2-reflection-v1/README.md) · [冻结 Experience](../experiences/experience-v002.json)

### 4. Validation Experience 对照

初始快照的公开元数据预检只命中 1/5 Validation 任务，因此付费实验在 API 调用前阻断。项目只使用 Train 来源修复检索元数据，冻结新的 Snapshot 后进行一次预注册公开审计，命中 4/5，随后执行 Baseline 与 Relevant 各 5 题×2 次，共 20 次正式对照。

| 指标 | Baseline | Relevant |
|---|---:|---:|
| Valid Runs | 10 / 10 | 10 / 10 |
| Resolved | 4 / 10 | 3 / 10 |
| Resolution Rate | 40% | 30% |
| Retrieval Hit | — | 8 / 10 |
| Measured Incremental Utilization | — | 0 |

唯一不一致结果发生在没有检索到 Experience 的任务；四个实际命中任务的配对成功分布完全相同。因此不能把总体 -10 个百分点归因于 Experience 造成退化，但同样没有净收益证据。Retriever 和 Snapshot 随后保持锁定，不再利用这批 Validation 调参。

证据：[Validation 对照报告](../experiments/benchmark-v2-experience-validation-paid-v1/README.md) · [机器可读比较](../experiments/benchmark-v2-experience-validation-paid-v1/comparison.json)

### 5. Experience 消费合同

Validation 表明“检索到”不等于“真正使用”。项目回到 Train-only 路径，为 7 条 Experience 增加 `Inspect → Act → Verify` 合同与可测行为目标，并在唯一具有跨任务检索命中的 Train holdout 上比较旧版自然语言 Experience 与结构化合同，两臂各运行 2 次。

两臂均为 1/2 Accepted，配对结果互换，增量利用仍为 0/2。结构化合同组的 Token、Tool Calls 和延迟较低，但单题两次只能作为描述性现象，不能证明成功率、遵循率或效率得到因果改善。

证据：[消费合同设计](../experiments/benchmark-v2-experience-consumption-v1/README.md) · [Train Holdout 结果](../experiments/benchmark-v2-experience-train-holdout-paid-v1/README.md)

### 6. Runtime Guardrail

对 holdout 公共轨迹的离线归因发现：两次运行共发生 11 次 `PATCH_APPLY_FAILED`，大量失败后没有重新读取当前文件就继续 Patch，另有一次 Accepted 轨迹没有运行测试。项目据此增加两类按 Experience 激活的 Runtime Guard：

- Patch 失败后，必须重新读取该 Diff 涉及的目标文件；读取无关文件不能解锁下一次 Patch。
- 最后一次成功编辑后必须运行测试，并在固定最大步数下预留验证窗口。

离线 FakeLLM 验证后，项目在同一个预注册 Train holdout 上执行 Control 与 Guardrail 各 2 次：

| 指标 | Control | Guardrail |
|---|---:|---:|
| Resolved | 1 / 2 | 2 / 2 |
| 实际执行的未重读 Patch | 9 | 0 |
| Runtime Contract Blocks | 0 | 4 |
| Test Executions | 2 | 5 |
| 平均 Tokens | 105,985.5 | 151,221.0 |
| 平均 Tool Calls | 18.0 | 24.0 |
| 平均延迟 | 65.8 s | 74.5 s |

两次目标违规尝试均在真正执行 Patch 前被阻断，Agent 随后重新读取并恢复，所以“Guardrail 能阻断目标违规”的机制结论成立。但只有一个不一致配对，exact McNemar `p=1.0`；两臂原本都完成了最终编辑验证和可测合同，增量利用仍为 0/2，Guardrail 还使用了更多资源。因此不能接受成功率或效率提升的因果结论。

证据：[Runtime Guardrail 设计](../experiments/benchmark-v2-experience-guardrails-v1/README.md) · [定向真实模型实验](../experiments/benchmark-v2-experience-guardrails-paid-v1/README.md) · [机器可读比较](../experiments/benchmark-v2-experience-guardrails-paid-v1/comparison.json)

### 7. Final Test

Final Test 只回答一个问题：冻结后的 `Experience + Runtime Contract` Candidate 是否优于无 Experience 的固定 Baseline。两臂使用相同模型、temperature、Policy、15 Steps、60,000 字符上下文、Tool Catalog、Docker Image 和 Independent Evaluator；唯一实验变量是 Experience Snapshot 与其激活的 Runtime Contract。

5 个 Test 任务每臂各运行 2 次，合计 20 次预注册调用；20/20 均进入独立评测，无补跑。

| 指标 | Baseline | Candidate | 差值 |
|---|---:|---:|---:|
| Resolved | 3 / 10 | 3 / 10 | 0 |
| Resolution Rate | 30% | 30% | 0 pp |
| Average ReAct Steps | 15.0 | 14.8 | -0.2 |
| Average Tool Calls | 22.0 | 23.3 | +1.3 |
| Average Tokens | 231,138.1 | 210,047.6 | -9.125% |
| Average Latency | 154.182 s | 139.278 s | -9.667% |

10 个逐 Run 配对中 Baseline 胜 2、Candidate 胜 2、平 6，exact McNemar `p=1.0`。Candidate 的 Retrieval Hit 与可测 Contract Adherence 都是 10/10，但 Incremental Utilization 为 0/10。较低的 Token 和 Latency 只是描述性点估计：样本小、主指标持平，而且 Tool Calls 增加，不能选择有利的辅助指标重新定义实验成功。

Final 轨迹中，Candidate 阻断了 2 次目标文件未重读重试和 8 次验证窗口违规，最终编辑已验证由 Baseline 8/10 变为 Candidate 9/10。这再次证明执行约束真实工作，但没有转化为净成功率收益。Test 在结果产生后关闭，不用于继续调整 Retriever、Experience、Prompt 或 Guardrail。

证据：[Final Test 报告](../experiments/benchmark-v2-final-test-v1/README.md) · [机器可读比较](../experiments/benchmark-v2-final-test-v1/comparison.json) · [Guardrail 行为归因](../experiments/benchmark-v2-final-test-v1/guardrail-behavior.json)

## 如何解释 V2

V2 没有证明“Experience 无效于所有任务”，也没有证明 Baseline 与 Candidate 永远等价。它证明的是：在当前冻结的 5 个 Test 任务、每臂每题 2 次的条件下，没有观察到净成功率提升。与此同时，实验定位了三个具体断点：检索命中不等于语义相关，Prompt 中出现经验不等于模型产生增量行为，过程 Guardrail 生效也不等于最终 Patch 正确。

因此，下一步若继续研究，应基于 Train/Validation 改进 Experience 的语义相关性、可执行表达与增量利用指标，并使用全新的未见任务评测；不能反复使用已经关闭的 V2 Test，直到出现满意数字。

## 可复验入口

以下检查不调用模型：

```powershell
python -m pytest
python -m ruff check .
python -m pip check
evodev-benchmark-qa --benchmark-root benchmarks-v2
```

V1 冻结结果还支持完整离线复算：

```powershell
evodev-final --project-root . --config configs/experiments/final-v1.yaml verify
```

真实模型实验会产生费用，历史冻结实验不应原地重跑或覆盖。

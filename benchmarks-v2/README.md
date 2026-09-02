# Benchmark v2 Implementation Status

该目录是已冻结的正式 Benchmark v2：18 道题已完成分 Split QA 和统一库存 QA，
`benchmark.yaml` 声明 8/5/5 Split 与类别配额，`manifest.json` 冻结每题任务树 checksum 和
全局 Manifest Hash。通用 `BenchmarkLoader` 可直接加载和验证该版本。

正式库存合同与逐题设计见：

- [`configs/benchmarks/v2-blueprint.yaml`](../configs/benchmarks/v2-blueprint.yaml)
- [`docs/BENCHMARK_V2_BLUEPRINT.md`](../docs/BENCHMARK_V2_BLUEPRINT.md)

当前已完成 8 道 Train 题：task_101–104 从已校准 Pilot 字节级迁移，task_105–108 为新实现。
Train 专项测试验证 8/8 Public 原始通过、8/8 Hidden 原始失败且 Gold 后通过；新四题的
8/8 不完整修复被 Hidden Tests 拒绝，完整专项 QA 独立重复 5/5 轮通过。规范化任务树哈希
和阶段结果见 [`train-qa.json`](train-qa.json)。

5 道 Validation 题 task_109–113 也已完成。专项测试验证 5/5 Public 原始通过、5/5 Hidden
原始失败且 Gold 后通过，并拒绝 10/10 个不完整修复；完整专项 QA 独立重复 5/5 轮通过。
该阶段未运行 Agent、未使用付费调试，任务树哈希与阶段结果见
[`validation-qa.json`](validation-qa.json)。

5 道 Test 题 task_114–118 已完成。专项测试验证 5/5 Public 原始通过、5/5 Hidden 原始失败且
Gold 后通过，并拒绝 10/10 个不完整修复；完整专项 QA 独立重复 5/5 轮通过。该阶段未运行
Agent、未使用付费调试，任务树哈希与阶段结果见 [`test-qa.json`](test-qa.json)。

统一 `evodev-benchmark-qa` 再次验证 18/18 原始 Hidden 失败且 Gold 后通过；18 个 Repository
Template 唯一且无跨 Split 泄漏，逐题 Agent Workspace 不包含 `task.yaml`、Hidden Tests 或
Gold Patch。正式冻结证据见 [`formal-qa.json`](formal-qa.json)，Manifest Hash 为
`c5ad46d8963400db6f31eeee64a0abe5029eeb1a4cee8e308af6a3e5f6c92ee6`。

Benchmark 库存冻结阶段没有运行 Coding Agent 或产生付费调用，因此该阶段不提供策略效果结论。

正式 Baseline 只运行 Train：task_101–108 每题重复 2 次，共 16 次固定 Policy 调用，不允许
选择性补跑。16/16 均完成独立评测，6/16 Resolved（37.5%）；task_101、102、104 均为
2/2，其余五题均为 0/2。Validation 与 Test 未参与本轮，也未用于调参。详见
[`BENCHMARK_V2_BASELINE_PLAN.md`](../docs/BENCHMARK_V2_BASELINE_PLAN.md)、
[`benchmark-v2-train-baseline-v1.yaml`](../configs/experiments/benchmark-v2-train-baseline-v1.yaml) 与
[`benchmark-v2-train-baseline-v1`](../experiments/benchmark-v2-train-baseline-v1/README.md)。
对应的 Train-only 失败证据见 [`evolution/benchmark-v2`](../evolution/benchmark-v2/README.md)。

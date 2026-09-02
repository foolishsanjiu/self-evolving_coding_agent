# Benchmark v2 Implementation Status

该目录是正式 Benchmark v2 的分阶段实现目录。当前只允许存在已完成离线 QA 的 Train 任务；
Validation/Test 尚未实现，因此这里暂不提供 `benchmark.yaml` 或 `manifest.json`，通用
`BenchmarkLoader` 也不会把该目录误识别为完整 Benchmark。

正式库存合同与逐题设计见：

- [`configs/benchmarks/v2-blueprint.yaml`](../configs/benchmarks/v2-blueprint.yaml)
- [`docs/BENCHMARK_V2_BLUEPRINT.md`](../docs/BENCHMARK_V2_BLUEPRINT.md)

当前已完成 8 道 Train 题：task_101–104 从已校准 Pilot 字节级迁移，task_105–108 为新实现。
Train 专项测试验证 8/8 Public 原始通过、8/8 Hidden 原始失败且 Gold 后通过；新四题的
8/8 不完整修复被 Hidden Tests 拒绝，完整专项 QA 独立重复 5/5 轮通过。规范化任务树哈希
和阶段结果见 [`train-qa.json`](train-qa.json)。

Validation/Test 仍未实现。只有在 18 道题全部通过离线 QA 后，才生成正式 Manifest。

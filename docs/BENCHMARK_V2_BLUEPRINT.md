# Benchmark v2 正式任务蓝图

本蓝图与正式 Manifest 共同冻结 Benchmark v2 的题目身份、Split、类别、难度、评测边界与任务树
Checksum。18 道题均已实现并通过离线 QA。机器可读规格位于
[`configs/benchmarks/v2-blueprint.yaml`](../configs/benchmarks/v2-blueprint.yaml)。

## 库存合同

| Split | 数量 | 使用边界 |
|---|---:|---|
| Train | 8 | 可用于失败分析、Experience 和 Policy Evidence |
| Validation | 5 | 只用于 Policy Pairwise Gate，不做付费调题 |
| Test | 5 | 冻结后只用于最终实验，不做付费调题 |

类别配额为：Cross-module Bug 4、State/Data Flow 3、Feature 3、Error Resilience 3、
Concurrency/Resource 2、Test Repair/Compatibility 3。全部题目为 Medium 或 Hard，不设置 Easy。

## 任务分配

| ID | Split | Category | Difficulty | Topic | Status |
|---|---|---|---|---|---|
| task_101 | Train | cross_module_bug | Medium | 完整请求维度缓存键 | Migrated + QA |
| task_102 | Train | state_data_flow | Medium | 不透明 cursor 遍历 | Migrated + QA |
| task_103 | Train | error_resilience | Medium | 类型化配置优先级 | Migrated + QA |
| task_104 | Train | state_data_flow | Hard | 库存预留异常补偿 | Migrated + QA |
| task_105 | Train | feature | Medium | 乱序分片组装 | Implemented + QA |
| task_106 | Train | cross_module_bug | Hard | 跨模块订阅按比例计费 | Implemented + QA |
| task_107 | Train | concurrency_resource | Hard | 有序有界并行映射 | Implemented + QA |
| task_108 | Train | test_repair_compatibility | Medium | Transport 协议兼容适配 | Implemented + QA |
| task_109 | Validation | cross_module_bug | Hard | 时区安全的 Token 过期判断 | Implemented + QA |
| task_110 | Validation | state_data_flow | Hard | 连续 ACK Checkpoint | Implemented + QA |
| task_111 | Validation | feature | Medium | HTTP ETag 条件刷新 | Implemented + QA |
| task_112 | Validation | error_resilience | Medium | 保留主异常的资源清理 | Implemented + QA |
| task_113 | Validation | test_repair_compatibility | Medium | 版本化序列化兼容 | Implemented + QA |
| task_114 | Test | cross_module_bug | Hard | 层级权限解析 | Implemented + QA |
| task_115 | Test | feature | Hard | 稳定依赖安装顺序 | Implemented + QA |
| task_116 | Test | error_resilience | Medium | 仅瞬态错误重试 | Implemented + QA |
| task_117 | Test | concurrency_resource | Hard | 可取消 Async Worker Pool | Implemented + QA |
| task_118 | Test | test_repair_compatibility | Medium | Plugin Hook 签名兼容 | Implemented + QA |

四道已校准 Pilot 题全部迁入 Train 候选；原 Pilot 目录中的 2/1/1 位置只是 Loader 合同，不延续到
正式 V2。正式 Validation/Test 的十道题均为全新 Repository Template，没有 Agent 历史运行。

## 每题实现与验收合同

每道题实现时必须同时具备：

1. 原始 Repository 的 Public Tests 全部通过，避免直接暴露故障位置；
2. 原始 Repository 在完整 Hidden Target/Regression Evaluation 中失败；
3. 应用 Gold Patch 后完整 Hidden Evaluation 通过；
4. 至少两个合理但不完整的修复被 Hidden Tests 拒绝；
5. Repository Template 不跨 Split，Hidden Tests 和 Gold Patch 不进入 Agent Workspace；
6. Gold Patch 只覆盖蓝图声明的最小修改范围，不顺带重构相邻代码。

18 道题已全部满足上述合同，正式 [`benchmarks-v2/manifest.json`](../benchmarks-v2/manifest.json)
已经生成并冻结。后续任何题目内容变化都会导致 `BenchmarkLoader.verify_manifest()` 失败。

## 后续实施顺序

1. **已完成**：构建并验证 Train task_105–108，同时把 task_101–104 迁入正式 Train；
2. **已完成**：独立构建 Validation task_109–113，只做离线 Gold/Hidden QA；
3. **已完成**：独立构建 Test task_114–118，只做离线 Gold/Hidden QA；
4. **已完成**：18 题完整库存 QA 通过并生成 Manifest；任何新的付费实验仍需单独授权。

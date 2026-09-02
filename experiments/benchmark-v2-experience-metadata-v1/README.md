# Benchmark v2 Train Experience Metadata

本目录冻结 `experience-v002` 的 Train-only 元数据修复。Reflection 模型生成的语义
`task_types` 被保留，同时从 Provenance 对应的 Train `task.yaml` 追加可信 Benchmark category；
没有重新调用模型，也没有修改 recommendation、rationale、confidence 或来源关系。

## 修复结果

| 项目 | v002 | v003 |
|---|---:|---:|
| Active Experience | 7 | 7 |
| Sources | 8 | 8 |
| 含可信源 category | 1 / 7 | 7 / 7 |
| Train leave-one-task-out hits | 0 / 8 | 1 / 8 |
| 有跨任务同类经验的 held-out hits | 0 / 1 | 1 / 1 |

唯一具备跨任务同类 Experience 的 Train holdout 是 task_101：它可以使用来自 task_106 的两条
`cross_module_bug` Experience。v003 对该任务稳定选择这两条经验，而 v002 没有命中。其他
Train 任务或者没有同类 Experience，或者 Experience 只来源于任务自身，因而被 Retriever 的
same-task 防泄漏规则排除。报告同时保留 1/8 和 1/1 两种分母，避免把稀疏库存描述成全面覆盖。

## 工程契约

`ReflectionExtractor` 现在在结构化输出通过安全校验后，自动把可信
`ReflectionContext.task_type` 加入候选 `task_types`。`add_source_task_types` 对历史冻结快照执行
同一条确定性规则，并在缺少任何 Source category 时拒绝迁移。新快照为
[`experience-v003`](../../experiences/experience-v003.json)，Canonical Hash 为
`53f8ce05c569b94f2969aacff64c43a799b19adec52cdad07a1f59611f1006e9`。

审计只读取 Train 公开任务元数据和公开仓库文件名；Validation/Test、hidden tests 与 Gold Patch
均未读取。下一阶段可以用 v003 执行一次此前已经冻结的 Validation 公共元数据预检，但在看到
结果后不得继续调节检索器；付费 Validation 仍需新的明确授权。

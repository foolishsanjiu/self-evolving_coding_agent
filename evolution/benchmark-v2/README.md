# Benchmark v2 Train Failure Evidence

本目录保存 `exp-baseline-v2-train-v1` 的离线 Train-only 失败聚合。输入只有冻结的 16-run
Baseline 轨迹与独立评测结果；没有调用模型，也没有读取 Validation/Test。

## 失败记账

| 类型 | Run 数 | Reflection 资格 | 平均 Patch Attempts |
|---|---:|:---:|---:|
| Target Test Failed | 4 | Yes | 5.75 |
| Regression Failed | 4 | Yes | 5.00 |
| Agent Max Steps | 1 | Yes | 8.00 |
| Syntax Error | 1 | No | 5.00 |
| 合计 | 10 | 9 eligible / 1 excluded | 5.60 |

确定性聚合报告位于
[`failure-patterns-baseline-v2-train-v1.json`](failure-patterns-baseline-v2-train-v1.json)。聚合器现在
同时记录总失败数、可学习失败数与排除项，避免 `SYNTAX_ERROR` 因不满足当前 Reflection 资格而
静默消失。

## 根因信号

逐 Run 审计见 [`failure-audit-v1.json`](failure-audit-v1.json)。主要信号为：

- 4 次需求维度覆盖不完整：只修正主路径或常见输入，遗漏非法域、边界或不支持的协议形态；
- 2 次实现未收尾：最终 Patch 只有准备性导入，或主成功路径没有返回完整结果；
- 2 次破坏注入资源的生命周期契约：两种并发实现重复假设 Executor 支持 context manager；
- 1 次步数耗尽且无最终 Patch；
- 1 次修改测试并留下语法错误，按当前规则明确排除出 Reflection 输入。

所有 10 个失败 Run 都在首次编辑前搜索代码并检查过测试，因此当前证据不支持继续把
`inspect_tests_before_edit` 或 `prefer_search_before_read` 作为下一优先变异。`max_react_steps`
值得进入候选考虑：完整 16-run 中有 10 次到达步数上限，且 `task_106_r02` 在 15 步结束时没有
可评测 Patch；但是否从 15 增加到 20 仍必须通过后续 Validation Gate，不能由 Train 直接晋升。

Experience 的优先方向应是跨任务策略，而不是题目答案：编辑前列出完整合同维度、保留注入资源
生命周期、在预算末段前固化可运行 Patch，以及提交前执行语法和回归验证。两次 `git_log` 未知
工具请求是次要工具目录漂移信号，调用失败被正常记录，但并非独立评测失败的直接原因。

## 边界与下一阶段

这些根因是基于 Patch、Trajectory Feature 和 Evaluator Output 的工程推断，不是付费 Reflection
模型的输出，也不证明任何候选策略必然提升成功率。后续已对 9 个 eligible Run 各执行一次付费
Reflection 调用：8 条通过安全校验，1 条被拒绝且未重试；经内容审计和一次重复归并，冻结为
7 条 active Experience。调用记账、结构化输出与边界见
[`experiments/benchmark-v2-reflection-v1`](../../experiments/benchmark-v2-reflection-v1/README.md)。
Validation/Test 在该阶段仍未访问。

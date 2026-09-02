# Benchmark v2 Train Baseline

本目录冻结 2026-09-02 对正式 Benchmark v2 Train 执行的固定 Policy Baseline。实验只收集
后续演化所需的 Train 失败证据，不访问 Validation/Test，也不是最终性能实验。

## 冻结条件

- Git Commit：`e02b7ece0d0494cf89b42b975a1f601395ca28f7`
- Benchmark：v2.0 Train，Manifest Hash
  `c5ad46d8963400db6f31eeee64a0abe5029eeb1a4cee8e308af6a3e5f6c92ee6`
- 模型：DeepSeek `deepseek-v4-flash`，temperature 0.1
- Policy：`fixed-react-v1`，最多 15 ReAct Steps，上下文预算 60,000 字符
- Experience：关闭
- Sandbox：`evodev-python:3.11`，Digest `sha256:52b485...65c3`
- 设计：task_101–108 每题独立运行 2 次，共 16 次付费调用
- 失败处理：不人工修补、不选择性补跑；16/16 均进入独立评测

完整机器可读条件见 [manifest.json](manifest.json)，逐次指标见 [summary.csv](summary.csv)。原始
`runs/` 与 `evaluation_runs/` 包含完整轨迹和 Docker 输出，按项目隐私与体积规则仅保存在本地；
本目录提交的是从原始证据提取并交叉核对的公开摘要。

## 结果

| Task | Repetition 1 | Repetition 2 | 稳定结果 |
|---|:---:|:---:|---|
| `task_101` | Resolved | Resolved | 2 / 2 |
| `task_102` | Resolved | Resolved | 2 / 2 |
| `task_103` | Target Failed | Target Failed | 0 / 2 |
| `task_104` | Resolved | Resolved | 2 / 2 |
| `task_105` | Target Failed | Regression Failed | 0 / 2 |
| `task_106` | Target Failed | Max Steps / no patch | 0 / 2 |
| `task_107` | Regression Failed | Regression Failed | 0 / 2 |
| `task_108` | Syntax Error | Regression Failed | 0 / 2 |

| 指标 | 结果 |
|---|---:|
| Resolved | 6 / 16 |
| Resolution Rate | 37.5% |
| 两次均解决的任务 | 3 / 8 |
| Average ReAct Steps | 13.5625 |
| Average Tool Calls | 20.875 |
| Average Tokens | 157,204.6875 |
| Average Latency | 111.891 s |
| Search Before Edit | 75% |
| Test Inspection Before Edit | 100% |
| Average Patch Attempts | 5.0 |

16 次轨迹合计 2,289,513 input tokens 和 225,762 output tokens，共 2,515,275 tokens。
执行发生在 DeepSeek 公布的峰值时段；按全部 input 均为 cache miss 保守估算约 1.3054 USD，
低于 2.00 USD 授权上限。该数值不是供应商账单，实际扣费未写入公开产物。

## 结论与边界

正式 V2 Train 对固定 Baseline 具有足够压力：五道题在两次运行中均未解决，可为 Reflection、
Experience 和 Policy Mutation 提供稳定失败证据。两次采样的解决结果完全一致，说明当前
3/8 的任务级覆盖不是由一次偶然成功构成；但两次重复仍不足以给出置信区间或模型通用能力结论。

`MAX_STEPS` 只是 Agent 终止状态，不等于独立评测失败：`task_104_r01` 到达 15 步后留下的补丁
仍通过评测；反过来，`task_105_r02` 正常结束但补丁触发 Regression Failure。最终成功只由 Fresh
Workspace 中的 Patch Apply、Syntax、Hidden Target 和 Hidden Regression Tests 决定。

本轮没有运行演化后 Policy，因而不能说明 Experience 或 Policy Evolution 是否有效。后续只能
使用这些 Train 轨迹生成候选；Validation 用于 Gate，Test 继续保持冻结，不能根据本结果调整。

离线失败聚合与逐 Run 根因审计已保存到
[`evolution/benchmark-v2`](../../evolution/benchmark-v2/README.md)：10 个失败中 9 个符合
Reflection 资格，1 个 Syntax Error 按当前规则明确排除。该聚合没有产生新的模型调用。

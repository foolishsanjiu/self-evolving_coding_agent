# Benchmark v2 Paid Pilot Calibration

本目录记录 2026-09-02 对 `benchmarks-pilot-v2` 执行的付费 Agent 难度校准。它只回答
“题目是否过于简单、能否对策略行为形成压力”，不是正式 Benchmark v2，也不是新的最终性能实验。

## 冻结条件

- Git Commit：`def7814a5ee234f3b7a61124adc09455a6162678`
- Benchmark：v2.0，Manifest Hash
  `6143ff702fffaf4f29b96ac65c222b85214ecaa6fa51cc777b623418a79285b1`
- 模型：DeepSeek `deepseek-v4-flash`，temperature 0.1
- Sandbox：`evodev-python:3.11`，Digest `sha256:52b485...65c3`
- Baseline：`policy-v001`，最多 15 ReAct Steps
- Champion：`policy-v003`，最多 10 ReAct Steps
- Experience：关闭
- 设计：两种 Policy 各运行 task_101–104 一次，共 8 次付费调用
- 失败处理：不人工修补、不选择性重跑；8/8 均为有效独立评测

完整机器可读条件见 [manifest.json](manifest.json)，逐次指标见 [summary.csv](summary.csv)。
原始 `runs/` 与 `evaluation_runs/` 含完整轨迹和 Docker 输出，按项目隐私/体积规则只保存在本地，
不纳入 Git；本目录提交的是从这些原始证据提取的固定摘要。

## 结果

| Task | Baseline | Champion | 区分结果 |
|---|:---:|:---:|---|
| `task_101` | Syntax Error | Accepted | Champion only |
| `task_102` | Accepted | Max Steps / no patch | Baseline only |
| `task_103` | Target Test Failed | Syntax Error | Neither |
| `task_104` | Accepted | Syntax Error | Baseline only |

| Variant | Resolved | Rate | Avg Steps | Avg Tokens | Avg Latency |
|---|---:|---:|---:|---:|---:|
| Baseline | 2 / 4 | 50% | 13.00 | 100,867 | 65.3 s |
| Champion | 1 / 4 | 25% | 10.00 | 62,039 | 49.1 s |

8 次轨迹合计记录 589,813 input tokens 和 61,812 output tokens，共 651,625 tokens。
公开轨迹不保存供应商账单与价格表，因此不推断人民币或美元成本。

`agent_status=MAX_STEPS` 不等于评测失败：Agent 到达步数上限后仍可能留下有效补丁，
例如 Baseline 的 `task_104` 最终通过独立评测。最终成功与否只以 Fresh Workspace 中的
Patch Apply、Syntax、Hidden Target 和 Hidden Regression Tests 为准。

## 结论与边界

Pilot 不是“太简单”：总体仅 3/8 Accepted，且没有任何一道题被两种 Policy 同时解决。
四题均能触发多轮检索、修改或验证，可继续作为正式 V2 **Train 候选难度锚点**；它们已经
参与校准，不能迁入正式 Validation/Test。

本轮不能证明 Champion 退化。`policy-v003` 平均步骤、Token 与延迟更低，但单题单次运行下
解决数也更低，特别是 10 步上限可能对复杂任务提前截断。样本只有 4 道题、每格 1 次，模型
随机性和题目构成影响很大；只有在冻结的更大任务集和重复运行中，才能比较稳定的策略效果。

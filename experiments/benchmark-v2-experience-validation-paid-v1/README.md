# Benchmark v2 Experience Validation Paid Comparison

本目录冻结 2026-09-02 执行的 Benchmark v2 Validation Baseline/Relevant 正式对照。执行合同、
授权、价格和 20 个 run 已在付费调用前提交为 Git `789f83a`；两组均为 5 题 × 2 次，所有结果
进入独立评测，没有选择性补跑。Test split 未运行，hidden tests 与 Gold Patch 未暴露给 Agent。

## 控制条件

两组使用相同的 DeepSeek `deepseek-v4-flash`、temperature 0.1、`fixed-react-v1` Policy、15 步
上限、60,000 字符上下文、MCP Tool Catalog、Docker Image/Digest 与 Benchmark Hash。唯一实验
变量是 Experience：Baseline 关闭，Relevant 使用冻结的 `experience-v003`，top-k 3、最多
2,500 字符。代码级 `assert_controlled_conditions` 已通过。

## 结果

| 指标 | Baseline | Relevant | Delta |
|---|---:|---:|---:|
| Valid Attempts | 10 / 10 | 10 / 10 | — |
| Resolved | 4 / 10 | 3 / 10 | -1 |
| Resolution Rate | 40% | 30% | -10 pp |
| Average ReAct Steps | 14.8 | 14.6 | -0.2 |
| Average Tool Calls | 22.2 | 21.3 | -0.9 |
| Average Tokens | 153,274.8 | 151,992.0 | -1,282.8 |
| Average Latency | 100.856 s | 90.740 s | -10.116 s |

逐任务配对如下：

| Task | Retrieval | Baseline | Relevant |
|---|:---:|:---:|:---:|
| task_109 | Hit | 0 / 2 | 0 / 2 |
| task_110 | Miss | 2 / 2 | 1 / 2 |
| task_111 | Hit | 2 / 2 | 2 / 2 |
| task_112 | Hit | 0 / 2 | 0 / 2 |
| task_113 | Hit | 0 / 2 | 0 / 2 |

10 对结果中 Baseline win 1、Relevant win 0、tie 9；双侧 exact McNemar p=1.0。唯一不一致发生
在未检索到 Experience 的 task_110 r01。四个实际命中 Experience 的任务共 8 对，成功分布
完全相同。因此总体 -10 pp 不能归因于 Experience 造成退化，但同样没有任何成功率提升证据。

## Retrieval 与利用

Relevant 检索命中 8/10（80%），但只有 2 个 run 的 Experience 含当前 Trace Analyzer 可测的
behavior target，且 0/2 出现相对 Baseline 的新行为，利用率为 0%。这说明 Train-only category
修复解决了“检索不到”的覆盖问题，却没有解决“经验是否被 Agent 采用”的行为转化问题。

本轮结论是 **不接受 Experience 带来净收益的假设**。不应继续用 Validation 调 Retriever、关键词
或 v003 内容，也不应为得到正结果而补跑。若继续研究，只能回到 Train 设计可执行、可测量的经验
表示与 Prompt 消费机制，再创建全新的实验版本；本 Validation 结果保持冻结。

## Token 与费用

两组合计 2,773,058 input tokens、279,610 output tokens，共 3,052,668 tokens。执行全部处于
DeepSeek 非峰时段；按全部 input 均为 cache miss 的保守估算为 **0.7946 USD**，低于 2.00 USD
授权上限。该金额是依据公开单价计算的上界，不是供应商账单。

机器可读比较见 [comparison.json](comparison.json)，原始文件 Hash 见
[evidence-manifest.json](evidence-manifest.json)。提交目录只保留公开摘要；完整轨迹与 Docker 输出
位于本地 gitignored `runs/` 和 `evaluation_runs/`。

后续状态：项目已回到 Train-only 路径，将自然语言经验迁移为结构化、可测量的 v004 消费合同，
详见 [`benchmark-v2-experience-consumption-v1`](../benchmark-v2-experience-consumption-v1/README.md)。
该工程升级没有改写本目录的 Validation 结果，也尚未产生新的性能结论。

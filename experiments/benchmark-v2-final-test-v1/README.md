# Benchmark v2 Final Test

本目录冻结 EvoDev 在 Benchmark v2 Test 上的终局、样本外系统对照。协议在任何付费调用前以
Git `dea968e` 冻结；随后严格执行 Baseline 10 次和 Candidate 10 次，20/20 均进入独立评测，
没有选择性补跑。Agent 从未接收 Gold Patch 或 hidden tests。

## 为什么是两臂

最终对照固定为无 Experience 的 `fixed-react-v1` Baseline 与当前完整候选
`experience-v005 + execution-contract-v2`。Train 上的 v004/v005 定向实验已经回答运行时门禁是否
真实阻断违规；Final Test 要回答的是“冻结后的完整 EvoDev 是否优于未演化 Baseline”。增加第三臂
会把调用从 20 次提高到 30 次，却不改变这个主要问题，因此不纳入终局设计。

## 冻结设计

| 项目 | Baseline | EvoDev candidate |
|---|---|---|
| Policy | `fixed-react-v1` | `fixed-react-v1` |
| Experience | disabled | `experience-v005`, relevant top-k 3 |
| Runtime contract | disabled | `execution-contract-v2` |
| Test tasks | `task_114`–`task_118` | 同左 |
| Repetitions | 每题 2 次 | 每题 2 次 |
| Paid calls | 10 | 10 |

两臂保持相同模型、temperature、15 Steps、60,000 字符上下文、MCP Tool Catalog、Docker 镜像和
独立评估器。20 个预注册 Run 必须全部进入评测；禁止根据中间结果选择性补跑。

## 费用预估

2026-09-02 重新核对 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：
`deepseek-v4-flash` 的缓存未命中输入/输出淡时价格为 0.22/0.66 USD 每百万 Token，峰时为
0.44/1.32 USD。按此前同为 20-call 的 Validation 对照实际用量外推，淡时约 0.7946 USD、峰时
约 1.5892 USD；即使 Token 翻倍且全部处于峰时，估算为 3.1785 USD。拟申请硬上限为 3.50 USD。

## 终局边界

- Test 任务和两臂在任何 Test Agent 结果出现前冻结；
- Agent 只接收公开题面、仓库和公开测试；hidden tests 只由独立评估器使用；
- `AGENT_ERROR` 等失败作为结果保留，不为改善分数选择性重跑；
- Test 结果无论正负均为终局结果，不再用 Test 调 Retriever、Experience、Prompt 或 Guardrail；
- 主要指标是独立评测 Resolution Rate，并报告逐题配对、exact McNemar、Token、步骤、工具调用、
  延迟、检索与合同指标；5 题×2 次不足以支持宽泛的因果优越性声明。

机器契约位于
[`benchmark-v2-final-test-v1.yaml`](../../configs/experiments/benchmark-v2-final-test-v1.yaml)，
执行前状态见 [preflight.json](preflight.json)。API Key、Docker 29.7.2 与固定沙箱镜像均已就绪；
用户明确授权 20 次调用和 3.50 USD 硬上限后才开始执行。

## 终局结果

| 指标 | Baseline | Candidate | Candidate - Baseline |
|---|---:|---:|---:|
| Valid attempts | 10 / 10 | 10 / 10 | — |
| Resolved | 3 / 10 | 3 / 10 | 0 |
| Resolution rate | 30% | 30% | 0 pp |
| 平均 ReAct Steps | 15.0 | 14.8 | -0.2 |
| 平均 Tool Calls | 22.0 | 23.3 | +1.3 |
| 平均 Tokens | 231,138.1 | 210,047.6 | -9.125% |
| 平均延迟 | 154.182 s | 139.278 s | -9.667% |

10 个逐 Run 配对中 Baseline 胜 2、Candidate 胜 2、平局 6，exact McNemar 双侧 p=1.0。
`task_114` 从 1/2 提高到 2/2，`task_116` 从 1/2 降至 0/2；`task_117` 两臂各 1/2，但成功发生
在不同重复。Candidate 检索 10/10、可测遵循 10/10，增量利用仍为 0/10。因此本 Test 不支持
“自演化候选提高成功率”的结论，也不能把较低 Token/延迟点估计解释为因果效率提升。

运行时归因显示 Candidate 共阻断 2 次目标文件未重读重试与 8 次验证窗口违规；最终编辑已验证
从 Baseline 8/10 变为 Candidate 9/10。Patch 重试恢复门禁只在检索到对应合同的 `task_114`
激活，其他任务的同类尝试不属于所选合同。这证明门禁路径继续真实生效，但没有转化为净成功率
收益。

两臂实际合计 3,996,951 Input Tokens、414,906 Output Tokens。全部运行处于 DeepSeek 淡时，
按所有输入均缓存未命中的保守估算为 1.1532 USD，低于 3.50 USD 授权上限。

机器比较见 [comparison.json](comparison.json)，行为归因见
[guardrail-behavior.json](guardrail-behavior.json)，证据 Hash 见
[evidence-manifest.json](evidence-manifest.json)。完整轨迹和评测输出仍保存在本地 gitignored 目录。
Test 至此关闭，无论结果正负均不再用于调整 Retriever、Experience、Prompt 或 Guardrail。

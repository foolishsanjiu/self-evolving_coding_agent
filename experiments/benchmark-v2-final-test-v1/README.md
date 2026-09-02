# Benchmark v2 Final Test Preflight

本目录冻结 EvoDev 在 Benchmark v2 Test 上的终局、样本外系统对照预案。当前只完成离线预检：
没有启动 Test Agent、没有调用模型、没有产生费用，也没有读取 Gold Patch 或 hidden tests。

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
离线状态见 [preflight.json](preflight.json)。当前 API Key 可用且官方文档列出目标模型，但
Docker Desktop 未运行；此外尚未获得这 20 次调用和 3.50 USD 上限的明确授权，因此停止在执行前。

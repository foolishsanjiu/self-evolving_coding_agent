# Benchmark v2 Experience Validation v2 Gate

本目录冻结 `experience-v003` 在 Benchmark v2 Validation **公开元数据**上的唯一一次决策审计。
审计门槛和 Retriever 身份已先由 Git 提交 `9224f0a` 固定，之后才执行审计；本轮没有调用模型、
没有启动 Docker，也没有读取 hidden tests、Gold Patch 或 Test split。

## 审计结果

| Validation Task | Category | Retrieval Hit | Selected | Prompt Chars |
|---|---|:---:|---:|---:|
| task_109 | cross_module_bug | Yes | 2 | 1,888 |
| task_110 | state_data_flow | No | 0 | 0 |
| task_111 | feature | Yes | 2 | 1,913 |
| task_112 | error_resilience | Yes | 1 | 819 |
| task_113 | test_repair_compatibility | Yes | 1 | 992 |

命中 **4/5** 个任务，共使用 **6** 条不同 Experience，单题最大注入 **1,913** 字符。三项指标
分别满足预先冻结的 `>= 4/5`、`>= 3` 和 `<= 2,500` 门槛，数据边界检查也通过。task_110
未命中是因为冻结库存中没有 `state_data_flow` 来源经验；该缺口不会再用 Validation 信息修补。

## 决策与锁定

状态为 `ready_for_paid_authorization`：只表示 Relevant arm 已具备足够处理差异，可以申请正式
付费对照，不是 Agent 性能提升结论，也不等于已经获得付费授权。Retriever、v003 快照、任务
类别、阈值和排序参数从本审计起全部锁定；任何后续修改都必须创建新的实验版本，不能沿用本 Gate。

若后续获得新的明确授权，冻结设计为 5 道 Validation、每题 2 次，Baseline/Relevant 各 10 次，
总计 20 次调用，禁止选择性补跑。执行前仍需核对当前模型价格、Docker 状态和离线 preflight。

原始输出见 [retrieval-audit.json](retrieval-audit.json)，机器可读判定见
[manifest.json](manifest.json)，审计前门槛见
[`benchmark-v2-experience-validation-v2.yaml`](../../configs/experiments/benchmark-v2-experience-validation-v2.yaml)。

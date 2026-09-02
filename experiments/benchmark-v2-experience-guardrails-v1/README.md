# Benchmark v2 Experience v005 Runtime Guardrails

本阶段只使用 v003/v004 Train holdout 的公开轨迹事件做离线失败归因，不调用模型、不运行 Docker，
也不读取 Validation/Test、hidden test 内容或 Gold Patch。目标不是根据单题改写答案，而是判断
结构化合同为什么没有稳定转化为行为。

## 失败归因

| 指标 | v003 两次合计 | v004 两次合计 |
|---|---:|---:|
| Patch Attempts | 10 | 16 |
| `PATCH_APPLY_FAILED` | 6 | 11 |
| 未重新读文件就再次 Patch | 3 | 8 |
| Test Calls | 5 | 4 |
| 实际执行的 Test Calls | 5 | 3 |
| 最终成功编辑未验证 | 0 | 1 |

v004 r01 共 10 次 Patch，其中 7 次失败，7 次都没有在下一次 Patch 前重新读取当前文件；最终
15 步耗尽且没有测试。v004 r02 有 4 次 Patch 失败，并包含一次无效测试参数；最终保留不完整
函数体并得到 Syntax Error。检索选择与合同渲染都正确，失败发生在 Prompt 之后的工具顺序层。

因此本轮拒绝“只把合同文案再写强一点”的 text-only v005。完整机器归因见
[attribution.json](attribution.json)。

## v005 最小改进

`experience-v005` 不修改任何 recommendation、rationale、task types、行为目标或 Sources，只为
v004 合同增加默认关闭、按快照激活的机器 guardrails：

- `inspect_after_patch_failure`：`PATCH_APPLY_FAILED` 后，在 `read_file` 成功前阻止下一次 Patch；
- `verify_after_last_edit`：最后一次成功编辑后，没有实际测试结果时拒绝 Final Answer；
- 验证窗口：倒数第二步已有未验证编辑时只允许测试，最后一步禁止创建无法再验证的新 Patch。

7/7 Experience 启用编辑后验证；只有已有对应恢复合同的
`exp_242f9076fcdd413085a70c719c9a07fc` 启用 Patch 失败恢复。新 consumer 为
`execution-contract-v2`，v001–v004 继续使用历史 consumer，默认 Agent 行为不变。

v005 Canonical Hash 为
`622a19135c144e1e9a8b1d787933add4a8299491888e6e31463c1bbc18919602`。Train leave-one-task-out
仍为 1/8，task_101 选择与 v004 相同的两条 Experience；加入可见 guardrail 说明后 Prompt 为
1,431 字符，低于 2,500 上限。确定性配置见
[`experience-v005-guardrails.yaml`](../../configs/experience-v005-guardrails.yaml)，机器迁移审计见
[guardrail-audit.json](guardrail-audit.json)，公开检索审计见
[train-retrieval-audit.json](train-retrieval-audit.json)。

## 结论与停止点

FakeLLM 单元测试已证明门禁能阻止连续失败 Patch、未经验证的 Final Answer、步数末尾的非验证
动作和最后一步的新 Patch。本阶段只证明机制确定、向后兼容且与轨迹根因一致；没有真实模型
调用，因此不宣称 v005 改善成功率、合同遵循率或成本。若要验证性能，必须另行冻结 v004/v005
Train holdout 对照并重新获得付费授权。

# Benchmark v2 Pilot

该目录是 Benchmark v2 的离线题目校准集，不是正式冻结的 Benchmark v2，也不参与
`final-v1`。四个任务用于在付费模型校准前验证题目结构、隐藏测试区分度和 Gold Patch。

目录中的 2 Train / 1 Validation / 1 Test 仅用于满足通用 Benchmark Loader 的完整 Split
合同；它们不是正式 V2 数据划分。Pilot 校准完成后，合格任务只考虑迁入正式 V2 Train，
正式 Validation/Test 将使用未参与 Pilot 调试的新任务。

| Task | Topic | Difficulty |
|---|---|---|
| `task_101` | 请求参数完整参与缓存键 | Medium |
| `task_102` | 跟随不透明分页游标 | Medium |
| `task_103` | 类型化配置优先级与布尔解析 | Medium |
| `task_104` | 多行库存预留失败补偿 | Hard |

离线验证：

```powershell
evodev-benchmark-qa --benchmark-root benchmarks-pilot-v2
python -m pytest tests/test_pilot_benchmark.py
```

当前 Manifest Hash：

```text
6143ff702fffaf4f29b96ac65c222b85214ecaa6fa51cc777b623418a79285b1
```

该阶段没有运行 Agent、没有产生 API 费用，也没有将任何隐藏测试或 Gold Patch 复制到
Agent Workspace。

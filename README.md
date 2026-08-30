# EvoDev

**EvoDev: An Evaluation-Driven Self-Evolving ReAct Coding Agent**

EvoDev 是一个面向软件开发任务的单 ReAct Agent。项目研究在底层 LLM 固定、
不进行模型微调的前提下，能否通过失败轨迹提取 Experience，并在受约束的 Policy
空间内进行可验证演化，从而提高编码任务解决率。

核心主线：`Build → Act → Measure → Improve → Prove`。

## 当前状态

当前已完成：

- **Task 1：Project Initialization**
- **Task 2：ReAct Loop + Native Tool Calling**
- **Task 3：Simplified Agent Harness**
- **Task 4：DevTools MCP Server**
- **Task 5：MCP Client + Dynamic Tool Discovery**
- **Task 6：Docker Sandbox + 完整 Coding Loop**
- **Task 7：Lightweight Trajectory Logging + Trace Analyzer**
- **Task 8：Benchmark v1.0（12 Tasks）**
- **Task 9：Independent Evaluator + Fixed-Policy Baseline**

现有能力：

- `src/` 可安装 Python 包骨架；
- YAML 与环境变量配置加载；
- `TaskSpec`、`ModelTurn` 等基础 Schema；
- OpenAI-compatible `LLMClient`，默认配置为 DeepSeek；
- 基础日志与真实模型 smoke 命令；
- 显式单 ReAct Tool Calling Loop；
- 可替换 `ToolProvider` 与 `NoOpEventSink`；
- `list_files`、`read_file`、`search_code`、`apply_patch`、`git_diff`、
  `run_tests` 六个 Native Tool；
- workspace 路径边界、结构化 ToolResult 和错误归一化；
- 基于官方 MCP Python SDK 2.x 的 DevTools stdio Server；
- Unified Diff 应用、Git Diff 获取和受控 pytest 路径/selector 执行；
- `fixtures/simple_bug` 的失败测试、补丁、diff、测试通过闭环；
- 可连接、断开和手动刷新的 `MCPToolProvider`；
- 支持分页发现与缓存的 Canonical `ToolSpec` Catalog；
- MCP Result 到 Canonical `ToolResult` 的归一化及分层错误统计；
- `AgentState` 统一任务生命周期和 Working Memory；
- `ContextManager` 基于字符预算确定性保留/压缩上下文；
- 仅针对只读、幂等工具瞬时错误的受限 Retry；
- 项目级 `FakeLLM` 与 `fixtures/simple_read` 开发 Fixture；
- 版本化 Run Metadata、追加式事件日志、Artifact 引用与崩溃恢复；
- 落盘前密钥脱敏，以及五项可复算 Trace Feature；
- 12 题受控 Python Coding Benchmark、严格 Loader 与 Agent 可见性隔离；
- Before-Fail / After-Gold-Pass QA、Task Checksum 与 Manifest Hash；
- Fresh Workspace + Docker 的独立分层 Evaluator 与失败分类；
- 受控实验 Manifest、指标汇总，以及冻结的 `exp-baseline-v1`。

真实模型 smoke call 需要本地 `LLM_API_KEY`，未配置密钥时不会自动调用或产生费用。

尚未实现 Experience 或 Policy Evolution。

## 环境

- Python 3.11
- Conda 管理基础环境
- pip 管理项目依赖
- Docker Desktop 或等价 Docker Engine（Task 6 起需要）

```powershell
conda env create -f environment.yml
conda activate evodev
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

已有环境只需执行后两条 pip 命令。

主要运行时依赖包括 OpenAI-compatible SDK、Pydantic、PyYAML、python-dotenv 和
`mcp>=2.1,<3`；完整版本约束以 `requirements.txt` 为准。

Task 6–9 没有新增 Python 依赖。Docker 必须能够同时访问 Client 与 Server：

```powershell
docker version
```

首次使用前，在项目根目录构建无运行时联网需求的测试镜像：

```powershell
docker pull python:3.11-slim
docker build -f docker/sandbox/Dockerfile -t evodev-python:3.11 .
```

镜像构建属于 Repository Preparation，可能需要联网拉取基础镜像和 pytest；Agent
执行测试时使用 `--pull never` 和 `--network none`，不会自由下载依赖。

## Disposable Workspace 与 Docker Sandbox

`WorkspaceManager` 将 Original Repository 复制到 `runs/run_<id>/workspace`，初始化独立
Git baseline，并支持：

- `create()`：创建当前 Run 独占的 workspace 与 artifacts 目录；
- `reset()`：恢复 baseline 并清除 workspace 内新增文件；
- `cleanup()`：先在 Run 根目录保存 `final.patch` 与 `final.diff`，再只删除 disposable workspace。

每次 `run_tests` 都启动一个具名的一次性容器。固定边界包括：

- 只挂载当前 disposable workspace 到 `/workspace`；
- `--network none`、`--pull never`、`--cap-drop ALL`；
- `no-new-privileges`、只读 rootfs，不挂载 Docker Socket；
- CPU 1、Memory 1 GiB、PID 128、默认超时 60 秒；
- 完整 stdout/stderr 写入 Run Artifact，模型侧只返回 20,000 字符以内的 head/tail。

超时后 runner 使用容器名执行强制删除并通过 `docker inspect` 复查。Sandbox 默认配置在
`configs/sandbox.yaml`。基础镜像只预装 pytest；其他 Benchmark 依赖应在准备阶段写入
镜像，运行阶段不允许自由 `pip install`、`curl` 或 `wget`。

## DevTools MCP Server

从项目根目录启动 stdio Server，并将工具限制在指定 workspace：

```powershell
python -m mcp_servers.devtools.server --workspace D:\path\to\workspace
```

该命令从 Task 6 起默认让 `run_tests` 进入 Docker。仅限本地开发、明确不需要隔离时可加
`--local-tests`；它不属于正式 Coding Run。

Server 暴露六个结构化工具：

- 只读：`list_files`、`read_file`、`search_code`、`git_diff`；
- 写入：`apply_patch`，仅接受 workspace 内的 Unified Git Diff；
- 执行：`run_tests`，仅接受测试路径与受限 pytest selector，不接受 Shell 命令。

当前 `run_tests` 通过 Task 6 的 Docker Sandbox 执行，并具有资源限制、超时、输出截断
与容器清理保证；`--local-tests` 仅用于明确选择的本地开发场景。

Agent 侧使用 `MCPToolProvider` 连接 Server；首次连接会分页发现工具并缓存，ReAct 每步
读取缓存，`refresh_tools()` 可显式刷新：

```python
from mcp import StdioServerParameters

from evodev.agent import ReActAgent
from evodev.tools import MCPToolProvider

server = StdioServerParameters(
    command="python",
    args=["-m", "mcp_servers.devtools.server", "--workspace", str(workspace_path)],
)
with MCPToolProvider(server) as tools:
    agent = ReActAgent(llm=llm, tool_provider=tools)
    result = agent.run(task)
```

`MCPToolProvider` 和 `NativeToolProvider` 实现同一个同步 `ToolProvider` 接口；MCP SDK
对象不会进入 ReAct 主循环。连接、超时、协议和 Server 退出错误与工具执行错误分别
计数，避免后续 Evaluation 把基础设施故障误判为 Agent 策略失败。

## Trajectory 与 Observability

每次运行使用独立的 `runs/run_<id>/` 目录，包含：

```text
run.json
events.jsonl
final.patch
final.diff
trace_features.json
artifacts/
```

`TrajectoryRecorder` 应在创建 `ReActAgent` 前初始化并作为 `event_sink` 注入。`run.json`
记录 Agent、Policy、Experience、模型、Prompt、工具目录、Benchmark 与 Sandbox 的版本或
哈希；工具目录哈希与工具发现顺序无关。`events.jsonl` 只持久化以下七类公开事件：

- `RUN_STARTED`、`MODEL_TURN`、`TOOL_CALL`、`TOOL_RESULT`；
- `FINAL_ANSWER`、`RUN_FINISHED`、`RUN_ERROR`。

`TOOL_CALL` 与 `TOOL_RESULT` 通过 `call_id` 关联。大输出写入 `artifacts/`，事件只保留
`artifact_ref`、`sha256`、`chars` 和 `truncated_for_llm`。Recorder 在落盘前过滤已知
API Key、Authorization Header、`.env` 密钥和值及常见 token/key 模式；disposable
workspace 也不会复制 `.env`。清理 workspace 时可传入相同过滤器：

```python
manager.cleanup(run, redact=recorder.redactor.redact_text)
```

事件采用 append、flush 与 `fsync`；重启时会截去尾部不完整 JSON 行并从下一序号继续。
`TraceAnalyzer` 仅从公开事件复算 `searched_before_edit`、`inspected_tests_before_edit`、
`unique_files_read`、`patch_attempts` 和 `test_runs`。轨迹格式版本为 `1.0`，不记录模型的
私有思维链。

## Benchmark v1.0

冻结的 Benchmark 位于 `benchmarks/`，包含恰好 12 个 Python Coding Tasks：

| Split | 数量 | 用途 |
|---|---:|---|
| Train | 6 | 失败轨迹、Reflection、Experience 与 Mutation Evidence |
| Validation | 3 | Candidate Policy Accept / Reject |
| Test | 3 | 最终报告，不参与调优 |

类别配额固定为 Bug Fix 4、Exception Handling 2、Feature 2、Refactoring 2、Test
Repair 2。每个任务包含 `task.yaml`、`repo/`、Hidden Target/Regression Tests 和
`gold.patch`。`BenchmarkLoader.create_agent_workspace()` 只从 `repo/` 创建 disposable
workspace，因此 Agent 看不到任务元数据之外的 Hidden Tests 与 Gold Patch。

`benchmarks/manifest.json` 冻结每题规范化 SHA-256 Checksum 和全局 Manifest Hash。
Loader 会验证 6/3/3 split、类别配额、Task ID 唯一性、必需资产以及同一 Repository
Template 不跨 split。运行 Benchmark QA：

```powershell
python -m pytest tests/test_benchmark.py -v
```

其中 12 个参数化用例分别在独立临时 Git workspace 中验证：

```text
Original Repository + Hidden Evaluation -> FAIL
Original Repository + Gold Patch + Hidden Evaluation -> PASS
```

## Independent Evaluation 与 Baseline

`IndependentEvaluator` 的 Agent 输入严格限制为 `task_id`、`final_patch` 和
`agent_run_id`。它从 Original Repository 创建新的评估 workspace，应用 Patch 后分别在
新 Docker 容器中执行 Syntax、Hidden Target Tests 和 Hidden Regression Tests。Agent
Final Answer、自测结论与原 Agent workspace 均不作为成功证据。

Grade 按以下顺序推进，全部通过才是 `RESOLVED`：

```text
PATCH_EXISTS -> PATCH_APPLIES -> SYNTAX_VALID
             -> TARGET_TESTS_PASS -> REGRESSION_TESTS_PASS
```

失败分类区分 Patch、Syntax、Target、Regression、Agent、Evaluation Timeout 与
Environment Error。`ExperimentReporter` 从公开 Trajectory 自动汇总 Resolution Rate、
ReAct Steps、Tool Calls、Tokens、Latency 与三项核心行为指标，并生成：

```text
evaluation_runs/exp_xxx/
├── manifest.json
├── summary.json
├── summary.csv
└── instances/task_xxx/
    ├── report.json
    ├── final.patch
    ├── test_output.txt
    └── trajectory_ref.json
```

已冻结的 `exp-baseline-v1` 使用 `deepseek-v4-flash`、temperature 0.1、固定 ReAct
Policy、每题一次，共 12 个有效评估：

| 指标 | 结果 |
|---|---:|
| Resolved | 9 / 12 |
| Task Resolution Rate | 75% |
| Average ReAct Steps | 9.25 |
| Average Tool Calls | 11.1667 |
| Average Tokens | 32,000.8333 |
| Average Latency | 25,056.9167 ms |
| Search-before-edit Rate | 41.67% |
| Test-inspection-before-edit Rate | 91.67% |
| Average Patch Attempts | 3.0833 |

未解决任务为 `task_002`、`task_008`、`task_010`，均为 `TARGET_TEST_FAILED`；没有
Regression、Timeout 或 Environment Failure。可审计冻结快照位于
`baselines/exp-baseline-v1/`，完整本地运行产物位于被 Git 忽略的 `runs/` 与
`evaluation_runs/`。再次运行会产生 API 费用：

```powershell
evodev-baseline --experiment-id exp-baseline-v1-new
```

## Reflection 与 Experience Store

Task 10 只对可归因于 Agent 策略的失败生成经验。`TARGET_TEST_FAILED`、
`REGRESSION_FAILED`、`AGENT_MAX_STEPS`、`PATCH_APPLY_FAILED` 与重复无效工具策略可进入
Reflection；Environment、Docker、MCP 连接和 API 故障不会污染 Experience Store。

每次反思调用只接收任务描述、评估失败类型、Patch 摘要、相关测试失败、五项行为特征和
至多 12 个重要事件。一次结构化模型调用同时返回两个独立校验的对象：解释本次失败的
`Reflection`，以及可跨任务复用的 `ExperienceCandidate`。Evidence 必须引用允许的
Trajectory Event、Behavioral Feature 或 Evaluator Result；具体任务答案、Gold Patch、
隐藏断言和精确常量修复会被拒绝。

SQLite Store 使用 `reflections`、`experiences`、`experience_sources` 三张表，支持
`candidate`、`active`、`deprecated` 生命周期，并保留 Experience → Reflection → Run →
Trajectory/Evaluation 的 Provenance。只有 Train 可写，Validation 与 Test 为只读。

从已完成的 Baseline 生成 Train Experience 会产生 API 费用。以下命令只处理
`task_002`；重复执行会跳过已经反思过的 Run：

```powershell
evodev-reflect --experiment-id exp-baseline-v1 --task-id task_002
```

默认数据库为被 Git 忽略的 `data/experience.sqlite`。Task 10 没有新增第三方依赖，SQLite
使用 Python 3.11 标准库。首次 Task 10 运行已对 `run_task_002_r01` 完成一次结构化调用：
输入 2,579 tokens、输出 2,389 tokens，落盘 1 条 Reflection、1 条 candidate Experience 和
1 条 Source Provenance。五个 Evidence Reference 均可在压缩上下文中解析，未检出具体
任务答案、期望异常文本、Gold Patch 或精确边界常量泄漏。

## 配置

普通配置位于 `configs/`：

- `configs/model.yaml`：模型提供方、模型名、温度和 API 地址；
- `configs/agent.yaml`：Agent 步数、工具重试和字符上下文预算。

密钥只从环境变量或本地 `.env` 读取：

```powershell
Copy-Item .env.example .env
```

随后填写：

```text
LLM_API_KEY=your-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

`.env` 已被 Git 忽略。`LLM_MODEL` 与 `LLM_BASE_URL` 会覆盖 YAML 默认值；配置对象只保存
密钥环境变量名，不保存密钥值。

## 验证

```powershell
python -m pytest
python -m ruff check .
```

当前离线测试覆盖：

- 配置与 Canonical Schema；
- LLM Provider Adapter；
- Native Tool 发现、调用和错误结果；
- 文件列表、分段读取、代码搜索和 workspace 逃逸防护；
- 直接回答、连续工具调用、同轮多工具调用和 Max Steps；
- Tool Failure 返回模型继续修正；
- EventSink Hook；
- AgentState 的文件、Patch、测试和错误状态更新；
- 上下文超预算后的确定性裁剪和旧 Observation 元数据压缩；
- 只读幂等 Retry、非幂等禁止 Retry、Tool/LLM Exception 状态化；
- FakeLLM 的确定性请求记录和错误路径；
- 六个 DevTools 的风险元数据、参数校验和归一化错误；
- Patch → Git Diff → pytest 的成功/失败/超时路径；
- MCP 进程内组件调用与真实 stdio 子进程传输；
- MCP Client connect/disconnect、分页终止、Catalog 缓存与手动刷新；
- Native/MCP Provider 语义一致性与 ReAct Agent 零修改替换；
- MCP Transport Error 与 Tool Execution Error 分层归一化和统计；
- Disposable Workspace create/reset/cleanup 与 Original Repository 不变性；
- Docker 参数边界、Artifact、输出截断、失败和超时清理语义；
- Simple Bug、Patch Failure、Test Failure、Infinite Test 四类多轮 Coding Loop；
- Run Metadata、事件顺序与 `call_id` 关联、Artifact 完整性和落盘脱敏；
- JSONL 尾部崩溃恢复、最终 Patch/Diff 脱敏及五项 Trace Feature 复算；
- Benchmark 固定规模与类别、Manifest 完整性和近重复 split 防泄漏；
- Agent Workspace 私有资产隔离及 12 题 Before-Fail / After-Gold-Pass QA；
- Gold、Empty、Invalid、Syntax 与 Regression Break 五类独立评估路径；
- Fresh Evaluation Workspace、分层 Grade、实验汇总与冻结 Baseline 一致性；
- Reflection Eligibility、压缩 Evidence Context 与一次调用双对象校验；
- Train-only Experience Store、相似经验合并、生命周期与 Provenance。

Docker 可用且镜像构建完成后，真实隔离验收为：

```powershell
python -m pytest tests/test_docker_integration.py -v
```

配置好密钥后，可执行一次真实模型调用：

```powershell
evodev-smoke-llm
```

预期模型回复：

```text
EvoDev ready
```

真实调用会产生 API 费用，因此不属于默认单元测试。

## v1.0 实施路线

1. ReAct Core：Task 1–3
2. MCP Coding Agent：Task 4–6
3. Trajectory 与 Independent Evaluation：Task 7–9
4. Experience Evolution：Task 10–11
5. Constrained Policy Evolution：Task 12–13
6. Final Controlled Experiment 与 CLI Demo：Task 14

项目严格遵循 Final v3.0 Scope Freeze，不在真实 Trace 和 Evaluation 证明需要前扩展范围。

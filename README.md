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
- 落盘前密钥脱敏，以及五项可复算 Trace Feature。

真实模型 smoke call 需要本地 `LLM_API_KEY`，未配置密钥时不会自动调用或产生费用。

尚未实现 Benchmark、Independent Evaluation、Experience 或 Policy Evolution。

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

Task 6 没有新增 Python 依赖。Docker 必须能够同时访问 Client 与 Server：

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
- EventSink Hook。
- AgentState 的文件、Patch、测试和错误状态更新；
- 上下文超预算后的确定性裁剪和旧 Observation 元数据压缩；
- 只读幂等 Retry、非幂等禁止 Retry、Tool/LLM Exception 状态化；
- FakeLLM 的确定性请求记录和错误路径。
- 六个 DevTools 的风险元数据、参数校验和归一化错误；
- Patch → Git Diff → pytest 的成功/失败/超时路径；
- MCP 进程内组件调用与真实 stdio 子进程传输。
- MCP Client connect/disconnect、分页终止、Catalog 缓存与手动刷新；
- Native/MCP Provider 语义一致性与 ReAct Agent 零修改替换；
- MCP Transport Error 与 Tool Execution Error 分层归一化和统计。
- Disposable Workspace create/reset/cleanup 与 Original Repository 不变性；
- Docker 参数边界、Artifact、输出截断、失败和超时清理语义；
- Simple Bug、Patch Failure、Test Failure、Infinite Test 四类多轮 Coding Loop；
- Run Metadata、事件顺序与 `call_id` 关联、Artifact 完整性和落盘脱敏；
- JSONL 尾部崩溃恢复、最终 Patch/Diff 脱敏及五项 Trace Feature 复算。

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

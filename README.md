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
- 项目级 `FakeLLM` 与 `fixtures/simple_read` 开发 Fixture。

真实模型 smoke call 需要本地 `LLM_API_KEY`，未配置密钥时不会自动调用或产生费用。

尚未实现 Docker Sandbox、持久化 Trajectory、Benchmark、Evaluation、Experience 或
Policy Evolution。

## 环境

- Python 3.11
- Conda 管理基础环境
- pip 管理项目依赖

```powershell
conda env create -f environment.yml
conda activate evodev
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

已有环境只需执行后两条 pip 命令。

主要运行时依赖包括 OpenAI-compatible SDK、Pydantic、PyYAML、python-dotenv 和
`mcp>=2.1,<3`；完整版本约束以 `requirements.txt` 为准。

## DevTools MCP Server

从项目根目录启动 stdio Server，并将工具限制在指定 workspace：

```powershell
python -m mcp_servers.devtools.server --workspace D:\path\to\workspace
```

Server 暴露六个结构化工具：

- 只读：`list_files`、`read_file`、`search_code`、`git_diff`；
- 写入：`apply_patch`，仅接受 workspace 内的 Unified Git Diff；
- 执行：`run_tests`，仅接受测试路径与受限 pytest selector，不接受 Shell 命令。

当前 `run_tests` 在宿主 Conda 环境内运行，并具有超时与输出截断；它尚不等同于安全
沙箱。容器化隔离将在 Task 6 实现。

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

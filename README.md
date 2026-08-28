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

现有能力：

- `src/` 可安装 Python 包骨架；
- YAML 与环境变量配置加载；
- `TaskSpec`、`ModelTurn` 等基础 Schema；
- OpenAI-compatible `LLMClient`，默认配置为 DeepSeek；
- 基础日志与真实模型 smoke 命令；
- 显式单 ReAct Tool Calling Loop；
- 可替换 `ToolProvider` 与 `NoOpEventSink`；
- `list_files`、`read_file`、`search_code` 三个只读 Native Tool；
- workspace 路径边界、结构化 ToolResult 和错误归一化；
- `fixtures/simple_read` 开发 Fixture 与 FakeLLM 测试。

真实模型 smoke call 需要本地 `LLM_API_KEY`，未配置密钥时不会自动调用或产生费用。

尚未实现写操作工具、Patch/Test 闭环、MCP、Docker Sandbox、持久化 Trajectory、
Benchmark、Evaluation、Experience 或 Policy Evolution。

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

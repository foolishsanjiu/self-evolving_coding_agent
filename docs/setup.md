# 环境配置与运行指南

本文包含 README 中下沉的 Conda、pip、Docker、密钥与运行说明。默认的离线测试和结果复验不会调用模型；所有真实模型入口都要求显式付费确认。

## 1. 基础环境

要求：

- Windows PowerShell（项目当前验证环境）或等价 Shell；
- Conda；
- Python 3.11；
- Git；
- Docker Desktop / Docker Engine，仅隔离测试和真实 Coding Run 需要。

首次创建环境：

```powershell
conda env create -f environment.yml
conda activate evodev
python -m pip install -e ".[dev]"
```

如果 `evodev` 环境已存在：

```powershell
conda activate evodev
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

运行时依赖的版本边界以 `pyproject.toml` 和 `requirements.txt` 为准；开发依赖以 `requirements-dev.txt` 为准。项目使用 Conda 管理 Python 基础环境，后续 Python 包由 pip 管理。

## 2. 离线验证

验证已提交的 V1 冻结结果不需要 API Key、Docker 或网络：

```powershell
evodev-final --project-root . --config configs/experiments/final-v1.yaml verify
```

当前冻结产物的预期结果包括：

```json
{
  "experiment_id": "final-v1",
  "verified_runs": 36,
  "verified_instances": 36,
  "verified_figures": 4,
  "summary_matches": true,
  "csv_matches": true,
  "valid": true
}
```

运行自动化测试、静态检查和依赖检查：

```powershell
python -m pytest
python -m ruff check .
python -m pip check
```

检查 V2 Benchmark 的冻结数据合同：

```powershell
evodev-benchmark-qa --benchmark-root benchmarks-v2
```

## 3. Docker Sandbox

首次使用前构建固定测试镜像：

```powershell
docker version
docker pull python:3.11-slim
docker build -f docker/sandbox/Dockerfile -t evodev-python:3.11 .
```

拉取基础镜像和构建阶段可能访问网络；Agent 的正式 `run_tests` 使用 `--pull never` 与 `--network none`，不会在任务运行时自由安装依赖。

Sandbox 默认配置位于 `configs/sandbox.yaml`，当前边界包括：

- 只挂载当前 Disposable Workspace；
- 禁用网络并使用只读 rootfs；
- 移除 Linux Capabilities，启用 `no-new-privileges`；
- 限制 CPU、内存、PID、执行时间和返回给模型的输出长度；
- 不挂载 Docker Socket、宿主源码或 `.env`。

Docker 共享宿主机内核，因此该 Sandbox 面向受控 Coding Task，不是恶意代码的完整安全边界。

## 4. 模型配置

复制本地环境变量模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中配置：

```text
LLM_API_KEY=your-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

`.env` 已被 Git 忽略。配置对象只保存密钥环境变量名，不把密钥值写入 Manifest；Trajectory Recorder 在落盘前还会对常见密钥模式和 Authorization Header 做脱敏。

可以先执行一次显式付费 Smoke Call：

```powershell
evodev-smoke-llm --confirm-paid
```

缺少 `--confirm-paid` 时，命令会在调用 Provider 前拒绝执行。

## 5. 运行单个 Coding Task

确保 Docker Desktop 已启动、固定镜像存在且 `.env` 已配置，然后执行：

```powershell
evodev-run `
  --project-root . `
  --benchmark-root benchmarks `
  --task benchmarks/test/task_010 `
  --policy policy-v003 `
  --confirm-paid
```

可选的 `--experience-snapshot experiences/experience-v001.json` 用于启用冻结 Experience。Single Task 结果写入独立目录，不会混入冻结 Final 结果；重复任务应使用新的唯一 Run ID。

## 6. MCP Server 调试

从项目根目录启动仅绑定指定 Workspace 的 DevTools stdio Server：

```powershell
python -m mcp_servers.devtools.server --workspace D:\path\to\workspace
```

正式 Coding Run 中的 `run_tests` 默认进入 Docker。`--local-tests` 只用于明确选择的本地开发场景，不属于冻结实验条件。

## 7. 付费与冻结实验边界

- 计划、QA、测试和 `verify` 默认不调用模型。
- 真实模型命令必须显式提供对应的付费确认参数。
- API Key 不应出现在命令行、日志、提交文件或 Benchmark Workspace 中。
- 已冻结的 Final 实验禁止选择性续跑；如果需要新的 Replication，应创建新的 Experiment Version、冻结新的 Commit 和 Run Matrix，而不是覆盖历史结果。
- V2 Test 已关闭，不能根据其结果继续调 Retriever、Experience、Prompt 或 Guardrail。

更完整的实验协议见 [Benchmark V2 评测复盘](evaluation_v2.md) 和 [技术报告](TECHNICAL_REPORT.md)。

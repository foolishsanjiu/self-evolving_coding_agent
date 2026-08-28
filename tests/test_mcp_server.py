from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from mcp_servers.devtools.server import build_server

FIXTURE = Path("fixtures/simple_read").resolve()
EXPECTED_TOOLS = {
    "list_files",
    "read_file",
    "search_code",
    "apply_patch",
    "git_diff",
    "run_tests",
}


def test_in_process_mcp_discovery_and_structured_result() -> None:
    async def exercise() -> None:
        async with Client(build_server(FIXTURE)) as client:
            listed = await client.list_tools()
            result = await client.call_tool("read_file", {"path": "README.md"})

        assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
        assert all(tool.annotations.open_world_hint is False for tool in listed.tools)
        assert result.structured_content["success"] is True
        assert result.structured_content["data"]["path"] == "README.md"
        assert "Simple Read Fixture" in result.structured_content["content"]

    asyncio.run(exercise())


def test_in_process_mcp_preserves_normalized_errors() -> None:
    async def exercise() -> None:
        async with Client(build_server(FIXTURE)) as client:
            result = await client.call_tool("read_file", {"path": "../README.md"})

        assert result.structured_content["success"] is False
        assert result.structured_content["error_type"] == "PATH_OUTSIDE_WORKSPACE"

    asyncio.run(exercise())


def test_real_stdio_transport() -> None:
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "mcp_servers.devtools.server",
                "--workspace",
                str(FIXTURE),
            ],
            cwd=str(Path.cwd()),
        )
        async with Client(parameters, read_timeout_seconds=10) as client:
            listed = await client.list_tools()
            result = await client.call_tool("list_files", {"recursive": True})

        assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
        assert "src/calculator.py" in result.structured_content["data"]["files"]

    asyncio.run(exercise())

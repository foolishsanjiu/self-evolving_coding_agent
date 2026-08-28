from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import StdioServerParameters
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from evodev.agent import AgentStatus, ReActAgent
from evodev.llm import FakeLLM, ModelTurn
from evodev.schemas import TaskSpec
from evodev.tools import MCPProviderError, MCPToolProvider, ToolCall
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider
from mcp_servers.devtools.server import build_server

FIXTURE = Path("fixtures/simple_read").resolve()


def _tool(name: str, *, next_page: bool = False) -> Tool:
    return Tool(
        name=name,
        description=f"{name} description",
        inputSchema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(
            readOnlyHint=not next_page,
            destructiveHint=next_page,
            idempotentHint=not next_page,
            openWorldHint=False,
        ),
    )


class FakeMCPClient:
    def __init__(
        self,
        pages: dict[str | None, ListToolsResult],
        response: CallToolResult | Exception | None = None,
        enter_error: Exception | None = None,
    ) -> None:
        self.pages = pages
        self.response = response or CallToolResult(
            content=[TextContent(type="text", text="plain result")],
            structuredContent={"value": 3},
        )
        self.enter_error = enter_error
        self.list_cursors: list[str | None] = []
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> FakeMCPClient:
        if self.enter_error:
            raise self.enter_error
        self.entered += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited += 1

    async def list_tools(
        self,
        *,
        cursor: str | None = None,
        cache_mode: str = "use",
    ) -> ListToolsResult:
        assert cache_mode == "reload"
        self.list_cursors.append(cursor)
        return self.pages[cursor]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
    ) -> CallToolResult:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _provider(client: FakeMCPClient) -> MCPToolProvider:
    return MCPToolProvider("fake", client_factory=lambda *args, **kwargs: client)


def test_connect_discovers_all_pages_caches_refreshes_and_disconnects() -> None:
    client = FakeMCPClient(
        {
            None: ListToolsResult(tools=[_tool("read")], nextCursor="page-2"),
            "page-2": ListToolsResult(tools=[_tool("write", next_page=True)]),
        }
    )
    provider = _provider(client)

    provider.connect()
    first_catalog = provider.list_tools()
    cached_catalog = provider.list_tools()
    refreshed_catalog = provider.refresh_tools()
    provider.disconnect()
    provider.connect()
    reconnected_catalog = provider.list_tools()
    provider.disconnect()

    assert [tool.name for tool in first_catalog] == ["read", "write"]
    assert cached_catalog == first_catalog == refreshed_catalog == reconnected_catalog
    assert client.list_cursors == [None, "page-2", None, "page-2", None, "page-2"]
    assert first_catalog[0].read_only and first_catalog[0].idempotent
    assert first_catalog[1].destructive and not first_catalog[1].read_only
    assert client.entered == 2 and client.exited == 2
    assert provider.connected is False


def test_repeated_pagination_cursor_is_protocol_error() -> None:
    client = FakeMCPClient(
        {
            None: ListToolsResult(tools=[], nextCursor="repeat"),
            "repeat": ListToolsResult(tools=[], nextCursor="repeat"),
        }
    )
    provider = _provider(client)

    with pytest.raises(MCPProviderError, match="repeated cursor") as error:
        provider.connect()

    assert error.value.error_type == "MCP_PROTOCOL_ERROR"
    assert provider.transport_error_counts == {"MCP_PROTOCOL_ERROR": 1}
    assert not provider.connected


def test_result_mapping_preserves_content_data_and_tool_error_layer() -> None:
    response = CallToolResult(
        content=[TextContent(type="text", text="fallback")],
        structuredContent={
            "success": False,
            "content": "missing file",
            "data": {"path": "missing.py"},
            "error_type": "FILE_NOT_FOUND",
            "duration_ms": 2,
        },
    )
    client = FakeMCPClient({None: ListToolsResult(tools=[_tool("read_file")])}, response)

    with _provider(client) as provider:
        result = provider.call_tool(
            ToolCall(call_id="missing", name="read_file", arguments={"path": "missing.py"})
        )

    assert not result.success
    assert result.content == "missing file"
    assert result.data == {"path": "missing.py"}
    assert result.error_type == "FILE_NOT_FOUND"
    assert provider.tool_error_counts == {"FILE_NOT_FOUND": 1}
    assert provider.transport_error_counts == {}


def test_transport_timeout_is_separate_from_tool_error() -> None:
    client = FakeMCPClient(
        {None: ListToolsResult(tools=[_tool("read_file")])},
        response=TimeoutError("server did not answer"),
    )

    with _provider(client) as provider:
        result = provider.call_tool(
            ToolCall(call_id="timeout", name="read_file", arguments={"path": "README.md"})
        )

    assert result.error_type == "MCP_TIMEOUT"
    assert provider.transport_error_counts == {"MCP_TIMEOUT": 1}
    assert provider.tool_error_counts == {}


def test_server_exit_is_a_transport_error() -> None:
    end_of_stream = type("EndOfStream", (Exception,), {})
    client = FakeMCPClient(
        {None: ListToolsResult(tools=[_tool("read_file")])},
        response=end_of_stream("server exited"),
    )

    with _provider(client) as provider:
        result = provider.call_tool(
            ToolCall(call_id="exit", name="read_file", arguments={"path": "README.md"})
        )

    assert result.error_type == "MCP_SERVER_EXITED"
    assert provider.transport_error_counts == {"MCP_SERVER_EXITED": 1}


def test_connection_failure_is_normalized_and_counted() -> None:
    client = FakeMCPClient({}, enter_error=OSError("cannot start server"))
    provider = _provider(client)

    with pytest.raises(MCPProviderError) as error:
        provider.list_tools()

    assert error.value.error_type == "MCP_CONNECTION_ERROR"
    assert provider.transport_error_counts == {"MCP_CONNECTION_ERROR": 1}


def _read_turn() -> ModelTurn:
    return ModelTurn(
        tool_calls=[
            ToolCall(
                call_id="read",
                name="read_file",
                arguments={"path": "README.md", "start_line": 1, "end_line": 2},
            )
        ]
    )


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="mcp-provider-parity",
        instruction="Read the fixture README.",
        workspace_path=FIXTURE,
    )


def test_native_and_mcp_providers_are_semantically_interchangeable() -> None:
    native = NativeToolProvider(DevToolsService(FIXTURE))
    mcp = MCPToolProvider(build_server(FIXTURE))
    native_result = ReActAgent(
        FakeLLM([_read_turn(), ModelTurn(content="done")]), native
    ).run(_task())
    with mcp:
        mcp_tools = mcp.list_tools()
        mcp_result = ReActAgent(
            FakeLLM([_read_turn(), ModelTurn(content="done")]), mcp
        ).run(_task())

    assert native_result.status == mcp_result.status == AgentStatus.SUCCESS
    assert {tool.name for tool in native.list_tools()} == {tool.name for tool in mcp_tools}
    assert native_result.tool_results[0].content == mcp_result.tool_results[0].content
    assert native_result.tool_results[0].data == mcp_result.tool_results[0].data


def test_mcp_provider_works_over_real_stdio() -> None:
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

    with MCPToolProvider(parameters, read_timeout_seconds=10) as provider:
        tools = provider.list_tools()
        result = provider.call_tool(
            ToolCall(call_id="stdio", name="list_files", arguments={"recursive": True})
        )

    assert len(tools) == 6
    assert result.success
    assert "src/calculator.py" in result.data["files"]

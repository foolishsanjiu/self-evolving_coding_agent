"""stdio MCP adapter for EvoDev's workspace-scoped development tools."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from evodev.tools import ToolCall
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider


class MCPToolResponse(BaseModel):
    """Structured MCP representation of the canonical EvoDev tool result."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    content: str
    data: dict[str, object] = Field(default_factory=dict)
    error_type: str | None = None
    duration_ms: int = Field(ge=0)


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
APPLY_PATCH = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
RUN_TESTS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)


def build_server(workspace_path: Path, test_timeout_seconds: float = 60) -> MCPServer:
    """Build a DevTools server bound to one workspace root."""
    provider = NativeToolProvider(
        DevToolsService(workspace_path, test_timeout_seconds=test_timeout_seconds)
    )
    server = MCPServer(
        name="evodev-devtools",
        instructions="Workspace-scoped coding tools for the EvoDev agent.",
    )

    def invoke(tool_name: str, arguments: dict[str, object]) -> MCPToolResponse:
        result = provider.call_tool(
            ToolCall(call_id=str(uuid4()), name=tool_name, arguments=arguments)
        )
        return MCPToolResponse(
            success=result.success,
            content=result.content,
            data=result.data,
            error_type=result.error_type,
            duration_ms=result.duration_ms,
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def list_files(path: str = ".", recursive: bool = False) -> MCPToolResponse:
        """List files under a workspace-relative directory."""
        return invoke("list_files", {"path": path, "recursive": recursive})

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def read_file(
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> MCPToolResponse:
        """Read a UTF-8 file using a one-based inclusive line range."""
        return invoke(
            "read_file",
            {"path": path, "start_line": start_line, "end_line": end_line},
        )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def search_code(query: str, path: str = ".", max_results: int = 50) -> MCPToolResponse:
        """Search UTF-8 workspace files for a literal text query."""
        return invoke(
            "search_code",
            {"query": query, "path": path, "max_results": max_results},
        )

    @server.tool(annotations=APPLY_PATCH, structured_output=True)
    def apply_patch(patch: str) -> MCPToolResponse:
        """Apply a workspace-contained unified Git patch."""
        return invoke("apply_patch", {"patch": patch})

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def git_diff() -> MCPToolResponse:
        """Return the current workspace Git diff and summary."""
        return invoke("git_diff", {})

    @server.tool(annotations=RUN_TESTS, structured_output=True)
    def run_tests(
        test_path: str | None = None,
        test_selector: str | None = None,
    ) -> MCPToolResponse:
        """Run pytest with an optional controlled path and selector."""
        return invoke(
            "run_tests",
            {"test_path": test_path, "test_selector": test_selector},
        )

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EvoDev DevTools MCP server.")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--test-timeout", type=float, default=60)
    arguments = parser.parse_args()
    build_server(arguments.workspace, arguments.test_timeout).run(transport="stdio")


if __name__ == "__main__":
    main()

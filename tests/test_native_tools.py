from pathlib import Path

from evodev.tools import ToolCall
from evodev.tools.devtools import DevToolsService
from evodev.tools.native import NativeToolProvider

FIXTURE = Path("fixtures/simple_read")


def _provider() -> NativeToolProvider:
    return NativeToolProvider(DevToolsService(FIXTURE))


def test_list_files_supports_shallow_and_recursive_modes() -> None:
    service = DevToolsService(FIXTURE)

    shallow = service.list_files()
    recursive = service.list_files(recursive=True)

    assert shallow["files"] == ["README.md"]
    assert recursive["files"] == [
        "README.md",
        "src/calculator.py",
        "tests/test_calculator.py",
    ]


def test_read_file_uses_one_based_inclusive_ranges() -> None:
    data = DevToolsService(FIXTURE).read_file("src/calculator.py", start_line=2, end_line=3)

    assert data["start_line"] == 2
    assert data["end_line"] == 3
    assert "Return the sum" in data["content"]
    assert "return left + right" in data["content"]


def test_search_code_returns_structured_matches() -> None:
    data = DevToolsService(FIXTURE).search_code("return left + right", path="src")

    assert data["truncated"] is False
    assert data["matches"][0]["file"] == "src/calculator.py"
    assert data["matches"][0]["line_number"] == 3
    assert "def add" in data["matches"][0]["small_context"]


def test_provider_discovers_six_tools_with_risk_metadata() -> None:
    tools = _provider().list_tools()

    assert [tool.name for tool in tools] == [
        "list_files",
        "read_file",
        "search_code",
        "apply_patch",
        "git_diff",
        "run_tests",
    ]
    by_name = {tool.name: tool for tool in tools}
    assert by_name["git_diff"].read_only and by_name["git_diff"].idempotent
    assert by_name["apply_patch"].destructive and not by_name["apply_patch"].idempotent
    assert not by_name["run_tests"].read_only and not by_name["run_tests"].destructive


def test_provider_rejects_invalid_arguments_before_execution() -> None:
    result = _provider().call_tool(
        ToolCall(
            call_id="invalid-range",
            name="read_file",
            arguments={"path": "README.md", "start_line": 3, "end_line": 1},
        )
    )

    assert result.success is False
    assert result.error_type == "INVALID_TOOL_ARGUMENTS"


def test_provider_normalizes_missing_file_error() -> None:
    result = _provider().call_tool(
        ToolCall(call_id="missing", name="read_file", arguments={"path": "missing.py"})
    )

    assert result.success is False
    assert result.error_type == "FILE_NOT_FOUND"


def test_provider_rejects_relative_and_absolute_workspace_escape() -> None:
    provider = _provider()
    outside_absolute = Path("README.md").resolve()

    relative_result = provider.call_tool(
        ToolCall(call_id="relative", name="read_file", arguments={"path": "../README.md"})
    )
    absolute_result = provider.call_tool(
        ToolCall(
            call_id="absolute",
            name="read_file",
            arguments={"path": str(outside_absolute)},
        )
    )

    assert relative_result.error_type == "PATH_OUTSIDE_WORKSPACE"
    assert absolute_result.error_type == "PATH_OUTSIDE_WORKSPACE"


def test_provider_rejects_unknown_tool() -> None:
    result = _provider().call_tool(ToolCall(call_id="unknown", name="shell", arguments={}))

    assert result.success is False
    assert result.error_type == "UNKNOWN_TOOL"

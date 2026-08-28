"""In-process provider for the initial read-only coding tools."""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from evodev.tools.contracts import ToolCall, ToolResult, ToolSpec
from evodev.tools.devtools import DevToolsService, PathOutsideWorkspaceError
from evodev.tools.provider import ToolProvider


class ListFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = "."
    recursive: bool = False


class ReadFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> ReadFileArguments:
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class SearchCodeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    path: str = "."
    max_results: int = Field(default=50, ge=1, le=100)


class NativeToolProvider(ToolProvider):
    """Validate and execute DevToolsService calls in the current process."""

    _argument_models: dict[str, type[BaseModel]] = {
        "list_files": ListFilesArguments,
        "read_file": ReadFileArguments,
        "search_code": SearchCodeArguments,
    }

    def __init__(self, service: DevToolsService) -> None:
        self.service = service
        self._tools = [
            ToolSpec(
                name="list_files",
                description="List files under a workspace-relative directory.",
                input_schema=ListFilesArguments.model_json_schema(),
                source="native",
                read_only=True,
                destructive=False,
                idempotent=True,
            ),
            ToolSpec(
                name="read_file",
                description="Read a UTF-8 file using a one-based inclusive line range.",
                input_schema=ReadFileArguments.model_json_schema(),
                source="native",
                read_only=True,
                destructive=False,
                idempotent=True,
            ),
            ToolSpec(
                name="search_code",
                description="Search UTF-8 workspace files for a literal text query.",
                input_schema=SearchCodeArguments.model_json_schema(),
                source="native",
                read_only=True,
                destructive=False,
                idempotent=True,
            ),
        ]

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def _failure(
        self,
        tool_call: ToolCall,
        error_type: str,
        message: str,
        started: float,
    ) -> ToolResult:
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=False,
            content=message,
            error_type=error_type,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        argument_model = self._argument_models.get(tool_call.name)
        if argument_model is None:
            return self._failure(
                tool_call, "UNKNOWN_TOOL", f"Unknown tool: {tool_call.name}", started
            )

        try:
            arguments = argument_model.model_validate(tool_call.arguments)
            method = getattr(self.service, tool_call.name)
            data = method(**arguments.model_dump())
        except ValidationError as exc:
            return self._failure(tool_call, "INVALID_TOOL_ARGUMENTS", str(exc), started)
        except PathOutsideWorkspaceError as exc:
            return self._failure(tool_call, "PATH_OUTSIDE_WORKSPACE", str(exc), started)
        except FileNotFoundError as exc:
            return self._failure(tool_call, "FILE_NOT_FOUND", str(exc), started)
        except NotADirectoryError as exc:
            return self._failure(tool_call, "NOT_A_DIRECTORY", str(exc), started)
        except PermissionError as exc:
            return self._failure(tool_call, "PERMISSION_DENIED", str(exc), started)
        except Exception as exc:
            return self._failure(tool_call, "TOOL_EXECUTION_ERROR", str(exc), started)

        content = json.dumps(data, ensure_ascii=False)
        return ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=True,
            content=content,
            data=data,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

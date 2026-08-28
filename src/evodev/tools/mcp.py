"""Synchronous ToolProvider adapter for an MCP client session."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Any, Protocol

from mcp import Client, MCPError
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from pydantic import ValidationError

from evodev.tools.contracts import ToolCall, ToolResult, ToolSpec
from evodev.tools.provider import ToolProvider


class MCPClientLike(Protocol):
    async def __aenter__(self) -> MCPClientLike: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    async def list_tools(
        self,
        *,
        cursor: str | None = None,
        cache_mode: str = "use",
    ) -> ListToolsResult: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
    ) -> CallToolResult: ...


class MCPProviderError(RuntimeError):
    """Provider lifecycle or discovery error with a normalized category."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class _Request:
    operation: Callable[[MCPClientLike], Awaitable[Any]]
    future: Future[Any]


class MCPToolProvider(ToolProvider):
    """Expose a persistent MCP connection through EvoDev's synchronous contract."""

    def __init__(
        self,
        target: Any,
        read_timeout_seconds: float = 30,
        client_factory: Callable[..., MCPClientLike] | None = None,
    ) -> None:
        if read_timeout_seconds <= 0:
            raise ValueError("read_timeout_seconds must be positive")
        self.target = target
        self.read_timeout_seconds = read_timeout_seconds
        self._client_factory = client_factory or Client
        self._requests: Queue[_Request | None] | None = None
        self._ready: Future[None] | None = None
        self._thread: Thread | None = None
        self._worker_error: BaseException | None = None
        self._tool_catalog: list[ToolSpec] = []
        self._connected = False
        self.transport_error_counts: Counter[str] = Counter()
        self.tool_error_counts: Counter[str] = Counter()

    @property
    def connected(self) -> bool:
        return self._connected

    def __enter__(self) -> MCPToolProvider:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.disconnect()

    async def _serve(self) -> None:
        assert self._ready is not None
        assert self._requests is not None
        client = self._client_factory(
            self.target,
            read_timeout_seconds=self.read_timeout_seconds,
        )
        try:
            await client.__aenter__()
            self._ready.set_result(None)
            while True:
                request = await asyncio.to_thread(self._requests.get)
                if request is None:
                    break
                try:
                    result = await request.operation(client)
                except BaseException as exc:
                    request.future.set_exception(exc)
                else:
                    request.future.set_result(result)
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                self._worker_error = exc
        finally:
            if self._ready.done() and self._ready.exception() is None:
                try:
                    await client.__aexit__(None, None, None)
                except BaseException as exc:
                    self._worker_error = self._worker_error or exc
            while True:
                try:
                    pending = self._requests.get_nowait()
                except Empty:
                    break
                if pending is not None and not pending.future.done():
                    pending.future.set_exception(
                        self._worker_error or RuntimeError("MCP client worker stopped")
                    )

    def _thread_main(self) -> None:
        asyncio.run(self._serve())

    def _submit(self, operation: Callable[[MCPClientLike], Awaitable[Any]]) -> Any:
        if not self._connected or self._requests is None:
            raise MCPProviderError("MCP_CONNECTION_ERROR", "MCP client is not connected")
        if self._worker_error is not None:
            raise self._worker_error
        if self._thread is None or not self._thread.is_alive():
            raise MCPProviderError("MCP_SERVER_EXITED", "MCP client worker stopped")
        future: Future[Any] = Future()
        self._requests.put(_Request(operation=operation, future=future))
        try:
            return future.result(timeout=self.read_timeout_seconds + 1)
        except TimeoutError:
            if self._worker_error is not None:
                raise self._worker_error
            if self._thread is None or not self._thread.is_alive():
                raise MCPProviderError("MCP_SERVER_EXITED", "MCP client worker stopped")
            raise

    def connect(self) -> None:
        """Open one persistent session and populate the tool catalog."""
        if self._connected:
            return
        self._requests = Queue()
        self._ready = Future()
        self._worker_error = None
        self._thread = Thread(target=self._thread_main, name="evodev-mcp-client", daemon=True)
        self._thread.start()
        try:
            self._ready.result()
            self._connected = True
            self.refresh_tools()
        except Exception as exc:
            error_type = self._error_type(exc, connecting=True)
            if not isinstance(exc, MCPProviderError):
                self.transport_error_counts[error_type] += 1
            self.disconnect()
            if isinstance(exc, MCPProviderError):
                raise
            raise MCPProviderError(error_type, str(exc)) from exc

    def disconnect(self) -> None:
        """Close the active session and clear connection-local catalog state."""
        requests = self._requests
        thread = self._thread
        self._connected = False
        self._tool_catalog = []
        if requests is not None and thread is not None and thread.is_alive():
            requests.put(None)
            thread.join()
        self._requests = None
        self._ready = None
        self._thread = None
        self._worker_error = None

    @staticmethod
    def _to_tool_spec(tool: Tool) -> ToolSpec:
        annotations = tool.annotations
        return ToolSpec(
            name=tool.name,
            description=tool.description or tool.title or tool.name,
            input_schema=tool.input_schema,
            source="mcp",
            read_only=(annotations.read_only_hint if annotations else False) or False,
            destructive=(annotations.destructive_hint if annotations else True) is not False,
            idempotent=(annotations.idempotent_hint if annotations else False) or False,
        )

    def refresh_tools(self) -> list[ToolSpec]:
        """Rediscover every tools/list page and atomically replace the cache."""

        async def discover(client: MCPClientLike) -> list[ToolSpec]:
            cursor: str | None = None
            seen_cursors: set[str] = set()
            discovered: list[ToolSpec] = []
            while True:
                page = await client.list_tools(cursor=cursor, cache_mode="reload")
                discovered.extend(self._to_tool_spec(tool) for tool in page.tools)
                cursor = page.next_cursor
                if cursor is None:
                    break
                if cursor in seen_cursors:
                    raise MCPProviderError(
                        "MCP_PROTOCOL_ERROR", "tools/list returned a repeated cursor"
                    )
                seen_cursors.add(cursor)
            names = [tool.name for tool in discovered]
            if len(names) != len(set(names)):
                raise MCPProviderError("MCP_PROTOCOL_ERROR", "Duplicate MCP tool name")
            return discovered

        try:
            catalog = self._submit(discover)
        except Exception as exc:
            error_type = self._error_type(exc)
            self.transport_error_counts[error_type] += 1
            if isinstance(exc, MCPProviderError):
                raise
            raise MCPProviderError(error_type, str(exc)) from exc
        self._tool_catalog = catalog
        return list(catalog)

    discover_tools = refresh_tools

    def list_tools(self) -> list[ToolSpec]:
        if not self._connected:
            self.connect()
        return list(self._tool_catalog)

    @staticmethod
    def _content_text(result: CallToolResult) -> str:
        text_parts = [item.text for item in result.content if isinstance(item, TextContent)]
        if text_parts:
            return "\n".join(text_parts)
        return json.dumps(
            [item.model_dump(mode="json", by_alias=True) for item in result.content],
            ensure_ascii=False,
        )

    def normalize_result(
        self,
        tool_call: ToolCall,
        result: CallToolResult,
        duration_ms: int,
    ) -> ToolResult:
        structured = result.structured_content
        if isinstance(structured, dict) and "success" in structured:
            structured_data = structured.get("data")
            if structured_data is None:
                data = {}
            elif isinstance(structured_data, dict):
                data = structured_data
            else:
                data = {"value": structured_data}
            success = bool(structured["success"]) and not result.is_error
            content = str(structured.get("content") or self._content_text(result))
            error_value = structured.get("error_type")
            error_type = str(error_value) if error_value else None
        else:
            if structured is None:
                data = {}
            elif isinstance(structured, dict):
                data = structured
            else:
                data = {"value": structured}
            success = not result.is_error
            content = self._content_text(result)
            error_type = None if success else "MCP_TOOL_ERROR"

        if not success and error_type is None:
            error_type = "MCP_TOOL_ERROR"

        normalized = ToolResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.name,
            success=success,
            content=content,
            data=data,
            error_type=error_type,
            duration_ms=duration_ms,
        )
        if not success:
            self.tool_error_counts[error_type or "MCP_TOOL_ERROR"] += 1
        return normalized

    @staticmethod
    def _error_type(exc: BaseException, connecting: bool = False) -> str:
        if isinstance(exc, MCPProviderError):
            return exc.error_type
        if isinstance(exc, BaseExceptionGroup):
            child_types = {
                MCPToolProvider._error_type(child, connecting) for child in exc.exceptions
            }
            for candidate in ("MCP_TIMEOUT", "MCP_SERVER_EXITED", "MCP_PROTOCOL_ERROR"):
                if candidate in child_types:
                    return candidate
        if isinstance(exc, TimeoutError):
            return "MCP_TIMEOUT"
        if type(exc).__name__ in {"BrokenResourceError", "ClosedResourceError", "EndOfStream"}:
            return "MCP_SERVER_EXITED"
        if isinstance(exc, (MCPError, ValidationError)):
            return "MCP_PROTOCOL_ERROR"
        if connecting or isinstance(exc, OSError):
            return "MCP_CONNECTION_ERROR"
        return "MCP_PROTOCOL_ERROR"

    def call_tool(self, tool_call: ToolCall) -> ToolResult:
        started = time.perf_counter()

        async def invoke(client: MCPClientLike) -> CallToolResult:
            return await client.call_tool(
                tool_call.name,
                tool_call.arguments,
                read_timeout_seconds=self.read_timeout_seconds,
            )

        try:
            if not self._connected:
                self.connect()
            result = self._submit(invoke)
        except Exception as exc:
            error_type = self._error_type(exc)
            self.transport_error_counts[error_type] += 1
            return ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.name,
                success=False,
                content=str(exc),
                error_type=error_type,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
        return self.normalize_result(
            tool_call,
            result,
            round((time.perf_counter() - started) * 1000),
        )

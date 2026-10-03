"""ToolClient (ported from M3 `mcp_client/client.py`): the suite's only path to the MCP tools.

Wraps `fastmcp.Client`. The target is "inprocess" (server built in this process, still spoken
to over the MCP protocol), a `.py` server script (stdio), an HTTP URL (`http://…/mcp`), or a
FastMCP object (tests).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from config.settings import get_settings

from .plan import ALL_TOOLS
from .server import Bundle, build_bundle

T = TypeVar("T")


class ToolCallError(Exception):
    def __init__(self, tool: str, message: str, *, retryable: bool) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message
        self.retryable = retryable


class UnexpectedToolError(RuntimeError):
    """The MCP server exposes a tool outside the allow-list (e.g. anything that sends email)."""


# --- in-process server cache (one per adapter mode + artifacts dir) ----------------------------
_bundles: dict[tuple[str, str], Bundle] = {}
_bundle_lock = threading.Lock()


def get_bundle(settings: Any | None = None) -> Bundle:
    s = settings or get_settings()
    key = (s.adapter_mode, str(s.artifacts_dir))
    with _bundle_lock:
        if key not in _bundles:
            _bundles[key] = build_bundle(s)
        return _bundles[key]


def reset_bundles() -> None:
    with _bundle_lock:
        _bundles.clear()
        _clients.clear()


def _target_from_settings(settings: Any) -> Any:
    target: str = settings.mcp_server_target
    if target == "inprocess":
        return get_bundle(settings).server
    if target.endswith(".py"):
        from fastmcp.client.transports import PythonStdioTransport

        # Pass the environment explicitly: the stdio client otherwise forwards only a minimal
        # safe set of variables and the server would miss its settings.
        return PythonStdioTransport(target, env=dict(os.environ))
    return target


def _result_data(res: Any) -> dict[str, Any]:
    data = getattr(res, "data", None)
    if isinstance(data, dict):
        return data
    structured = getattr(res, "structured_content", None)
    if isinstance(structured, dict):
        inner = structured.get("result")
        return inner if isinstance(inner, dict) and len(structured) == 1 else structured
    for block in getattr(res, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _input_schema(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return dict(schema or {"type": "object", "properties": {}})


class ToolClient:
    def __init__(self, target: Any, *, call_timeout_s: float = 10.0) -> None:
        self._target = target
        self._timeout_s = call_timeout_s
        self._declarations: list[dict[str, Any]] | None = None

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> ToolClient:
        s = settings or get_settings()
        return cls(_target_from_settings(s), call_timeout_s=s.mcp_call_timeout_s)

    def _client(self) -> Any:
        from fastmcp import Client

        return Client(self._target)  # fresh per call: safe across event loops / threads

    async def list_tools(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            tools = await c.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "parameters": _input_schema(t)}
            for t in tools
        ]

    async def declarations(self) -> list[dict[str, Any]]:
        """Tool discovery (cached). Fails if the server exposes anything off the allow-list."""
        if self._declarations is None:
            decls = await self.list_tools()
            unexpected = sorted(
                d["name"] for d in decls if d["name"] not in ALL_TOOLS or "send" in d["name"]
            )
            if unexpected:
                raise UnexpectedToolError(f"MCP server exposes unexpected tools: {unexpected}")
            self._declarations = decls
        return self._declarations

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        from fastmcp.exceptions import ToolError

        await self.declarations()
        try:
            async with self._client() as c:
                res = await asyncio.wait_for(c.call_tool(tool, args), timeout=self._timeout_s)
        except ToolError as e:
            msg = str(e)
            raise ToolCallError(tool, msg, retryable="retryable:" in msg) from e
        except TimeoutError as e:
            raise ToolCallError(tool, "timeout", retryable=True) from e
        except UnexpectedToolError:
            raise
        except Exception as e:  # transport / connection / schema validation problems
            msg = f"{type(e).__name__}: {e}"
            retryable = not ("validation" in msg.lower() or "permanent:" in msg)
            raise ToolCallError(tool, msg, retryable=retryable) from e
        if getattr(res, "is_error", False):
            text = " ".join(getattr(b, "text", "") or "" for b in res.content or [])
            raise ToolCallError(tool, text, retryable="retryable:" in text)
        return _result_data(res)


_clients: dict[tuple[str, str, str], ToolClient] = {}


def get_client(settings: Any | None = None) -> ToolClient:
    """One cached ToolClient per adapter mode / artifacts dir / target (keeps discovery cached)."""
    s = settings or get_settings()
    key = (s.adapter_mode, str(s.artifacts_dir), s.mcp_server_target)
    with _bundle_lock:
        client = _clients.get(key)
    if client is None:
        client = ToolClient.from_settings(s)
        with _bundle_lock:
            _clients[key] = client
    return client


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from sync code (Streamlit, voice hook); safe inside a running loop too."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def call_tool(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Synchronous convenience: one MCP tool call through the settings-selected transport."""
    return run_sync(get_client().call(tool, args))

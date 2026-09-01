"""최소 MCP stdio 클라이언트 (JSON-RPC 2.0, 줄 단위).

외부 SDK 의존 없이 stdio MCP 서버를 띄워 initialize → tools/list → tools/call 한다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gigachanie.mcp.config import MCPServerConfig

_PROTOCOL_VERSION = "2025-06-18"
_TIMEOUT = 30.0


class MCPError(RuntimeError):
    pass


@dataclass
class MCPTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified(self) -> str:
        return f"{self.server}_{self.name}"


class _StdioClient:
    def __init__(self, cfg: MCPServerConfig, root: Path) -> None:
        self._cfg = cfg
        self._root = root
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0

    async def start(self) -> None:
        env = {**os.environ, **self._cfg.env}
        cwd = str((self._root / self._cfg.cwd).resolve()) if self._cfg.cwd else str(self._root)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._cfg.command,
                *self._cfg.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                cwd=cwd,
            )
        except (OSError, ValueError) as exc:
            raise MCPError(f"서버 '{self._cfg.name}' 를 시작할 수 없습니다: {exc}") from exc

        self._reader_task = asyncio.create_task(self._read_loop())
        await self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "gigachanie", "version": "0.0.1"},
            },
        )
        await self._notify("notifications/initialized")

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list", {})
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        parts: list[str] = []
        for item in result.get("content", []) or []:
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(f"[{item.get('type', 'content')}]")
        return "\n".join(parts) or "(빈 결과)", bool(result.get("isError", False))

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            if self._proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()

    # ------------------------------------------------------------- 내부

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            mid = msg.get("id")
            if mid is not None and mid in self._pending:
                fut = self._pending.pop(mid)
                if not fut.done():
                    fut.set_result(msg)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("서버가 시작되지 않았습니다.")
        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        mid = self._next_id
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self._send(
            {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
        )
        try:
            msg = await asyncio.wait_for(fut, timeout=_TIMEOUT)
        except TimeoutError as exc:
            self._pending.pop(mid, None)
            raise MCPError(f"'{method}' 응답 시간 초과") from exc
        if "error" in msg:
            err = msg["error"]
            raise MCPError(f"{method}: {err.get('message', err)}")
        return msg.get("result", {}) if isinstance(msg.get("result"), dict) else {}


@dataclass
class MCPServerHandle:
    name: str
    tools: list[MCPTool] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class MCPManager:
    """설정된 모든 MCP 서버를 시작하고 도구를 모은다."""

    def __init__(self, configs: list[MCPServerConfig], root: Path) -> None:
        self._configs = [c for c in configs if not c.disabled]
        self._root = root
        self._clients: dict[str, _StdioClient] = {}
        self.handles: list[MCPServerHandle] = []

    async def start(self) -> list[MCPServerHandle]:
        self.handles = []
        for cfg in self._configs:
            client = _StdioClient(cfg, self._root)
            handle = MCPServerHandle(name=cfg.name)
            try:
                await client.start()
                raw = await client.list_tools()
                handle.tools = [
                    MCPTool(
                        server=cfg.name,
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema") or {"type": "object", "properties": {}},
                    )
                    for t in raw
                    if t.get("name")
                ]
                self._clients[cfg.name] = client
            except MCPError as exc:
                handle.error = str(exc)
                with contextlib.suppress(Exception):
                    await client.stop()
            self.handles.append(handle)
        return self.handles

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        client = self._clients.get(server)
        if client is None:
            return f"MCP 서버 '{server}' 가 실행 중이 아닙니다.", True
        try:
            return await client.call_tool(tool, arguments)
        except MCPError as exc:
            return str(exc), True

    async def stop(self) -> None:
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.stop()
        self._clients.clear()

    @property
    def all_tools(self) -> list[MCPTool]:
        return [t for h in self.handles for t in h.tools]

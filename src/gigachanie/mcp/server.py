"""GigaChanie 도구를 MCP(stdio JSON-RPC 2.0)로 외부 에이전트에 제공한다.

`giga mcp serve` 로 실행하면 Claude Desktop 같은 MCP 클라이언트가
GigaChanie 의 read_file·grep·(옵션) write_file 등을 도구로 쓸 수 있다.
stdout 에는 JSON-RPC 만 나가고 로그는 stderr 로 간다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from gigachanie import __version__
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext, ToolError
from gigachanie.serving.base import run_sync

_PROTOCOL_VERSION = "2025-06-18"


class MCPServer:
    def __init__(
        self,
        root: Path,
        *,
        write: bool = False,
        web: bool = False,
        instream: TextIO | None = None,
        outstream: TextIO | None = None,
        log: TextIO | None = None,
    ) -> None:
        self._root = root.resolve()
        self._in = instream if instream is not None else sys.stdin
        self._out = outstream if outstream is not None else sys.stdout
        self._log = log if log is not None else sys.stderr
        self._running = True
        self._registry = build_registry(writable=write, web=web)
        # MCP 는 대화형 승인 콜백을 걸 수 없다. write 를 켜면 full-auto.
        # (MCP 클라이언트가 자체 도구 승인 UI 를 가진다는 전제)
        self._ctx = ToolContext(
            root=self._root,
            policy=ApprovalPolicy(
                mode=ApprovalMode.FULL_AUTO if write else ApprovalMode.SUGGEST
            ),
            allow_network=web,
        )

    # ------------------------------------------------------------------ io

    def _write(self, obj: dict[str, Any]) -> None:
        self._out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._out.flush()

    def _reply(self, mid: Any, result: dict[str, Any]) -> None:
        if mid is not None:
            self._write({"jsonrpc": "2.0", "id": mid, "result": result})

    def _error(self, mid: Any, code: int, message: str) -> None:
        if mid is not None:
            self._write(
                {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
            )

    def _logline(self, msg: str) -> None:
        try:
            self._log.write(f"[giga mcp serve] {msg}\n")
            self._log.flush()
        except (OSError, ValueError):
            pass

    # --------------------------------------------------------------- 루프

    def serve_forever(self) -> None:
        tool_names = ", ".join(self._registry.names())
        self._logline(f"준비됨 · 도구 {len(self._registry)}개: {tool_names}")
        while True:
            raw = self._in.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict):
                self._dispatch(msg)
            if not self._running:
                break

    def _dispatch(self, msg: dict[str, Any]) -> None:
        mid = msg.get("id")
        method = str(msg.get("method", ""))
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "initialize":
            self._reply(
                mid,
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "gigachanie", "version": __version__},
                },
            )
        elif method in ("notifications/initialized", "notifications/cancelled"):
            pass  # 알림 — 응답 없음
        elif method == "ping":
            self._reply(mid, {})
        elif method == "tools/list":
            self._reply(mid, {"tools": self._tool_specs()})
        elif method == "tools/call":
            self._call_tool(mid, params)
        elif method == "shutdown":
            self._running = False
            self._reply(mid, {})
        else:
            self._error(mid, -32601, f"지원하지 않는 메서드: {method}")

    def _tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.parameters
                or {"type": "object", "properties": {}},
            }
            for spec in self._registry.specs()
        ]

    def _call_tool(self, mid: Any, params: dict[str, Any]) -> None:
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        tool = self._registry.get(name)
        if tool is None:
            self._error(mid, -32602, f"알 수 없는 도구: {name}")
            return
        try:
            result = run_sync(tool.run(args, self._ctx))
        except ToolError as exc:
            self._reply(
                mid,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
            return
        except Exception as exc:  # noqa: BLE001
            self._logline(f"도구 '{name}' 예외: {exc}")
            self._error(mid, -32000, f"도구 실행 오류: {exc}")
            return
        self._reply(
            mid,
            {
                "content": [{"type": "text", "text": result.content}],
                "isError": result.is_error,
            },
        )

"""MCP 도구를 GigaChanie 도구 레지스트리에 등록한다."""

from __future__ import annotations

from typing import Any

from gigachanie.loop.approval import ApprovalRequest
from gigachanie.loop.tools import ToolContext, ToolFunc, ToolRegistry, ToolResult
from gigachanie.mcp.client import MCPManager, MCPTool


def _make_runner(manager: MCPManager, tool: MCPTool) -> ToolFunc:
    async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        summary = f"MCP {tool.server}.{tool.name}"
        allowed, reason = ctx.policy.check(
            ApprovalRequest(kind="network", summary=summary, detail=str(args)[:2000])
        )
        if not allowed:
            return ToolResult.error(f"{summary} 거부됨 ({reason})")
        text, is_error = await manager.call(tool.server, tool.name, args)
        return ToolResult(content=text, is_error=is_error)

    return run


def register_mcp_tools(reg: ToolRegistry, manager: MCPManager) -> int:
    """실행 중인 MCP 서버들의 도구를 등록한다. 등록된 도구 수 반환."""
    n = 0
    for tool in manager.all_tools:
        schema = tool.input_schema
        if not isinstance(schema, dict) or "type" not in schema:
            schema = {"type": "object", "properties": {}}
        desc = tool.description or f"{tool.server} 서버의 {tool.name}"
        reg.register_func(
            tool.qualified,
            f"[MCP:{tool.server}] {desc}"[:400],
            schema,
            _make_runner(manager, tool),
        )
        n += 1
    return n

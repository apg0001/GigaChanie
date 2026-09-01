"""MCP(Model Context Protocol) 클라이언트.

외부 MCP 서버(stdio)를 띄워 그 도구를 GigaChanie 도구로 노출한다.
설정은 Claude Code 호환 `.mcp.json` / `mcp.json` 형식.
"""

from gigachanie.mcp.client import MCPManager, MCPServerHandle
from gigachanie.mcp.config import MCPServerConfig, load_mcp_config

__all__ = [
    "MCPManager",
    "MCPServerHandle",
    "MCPServerConfig",
    "load_mcp_config",
]

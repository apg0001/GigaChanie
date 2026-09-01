"""MCP 서버 설정 로드 (Claude Code 호환).

우선순위: 사용자(`~/.config/gigachanie/mcp.json`) < 프로젝트(`<root>/.mcp.json`
또는 `<root>/.agent/mcp.json`). 같은 이름이면 뒤가 이김.

형식:
    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
          "env": { "FOO": "bar" }
        }
      }
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_path


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    disabled: bool = False


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers") or data.get("servers") or {}
    return servers if isinstance(servers, dict) else {}


def _sources(root: Path) -> list[Path]:
    return [
        user_config_path("gigachanie", appauthor=False, ensure_exists=False) / "mcp.json",
        root / ".mcp.json",
        root / ".agent" / "mcp.json",
    ]


def load_mcp_config(root: Path) -> list[MCPServerConfig]:
    merged: dict[str, Any] = {}
    for src in _sources(root):
        for name, spec in _read(src).items():
            if isinstance(spec, dict):
                merged[name] = spec

    out: list[MCPServerConfig] = []
    for name, spec in merged.items():
        cmd = spec.get("command")
        if not cmd:
            continue
        out.append(
            MCPServerConfig(
                name=name,
                command=str(cmd),
                args=[str(a) for a in spec.get("args", [])],
                env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                cwd=spec.get("cwd"),
                disabled=bool(spec.get("disabled", False)),
            )
        )
    return out

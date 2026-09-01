"""MCP 클라이언트 / 설정 / 도구 등록 테스트 (mock stdio 서버 사용)."""

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.tools import ToolContext, ToolRegistry
from gigachanie.mcp import MCPManager, load_mcp_config
from gigachanie.mcp.config import MCPServerConfig
from gigachanie.mcp.tools import register_mcp_tools
from gigachanie.serving.base import run_sync

runner = CliRunner()
_MOCK = str(Path(__file__).parent / "mcp_mock_server.py")


def _mock_cfg() -> MCPServerConfig:
    return MCPServerConfig(name="mock", command=sys.executable, args=[_MOCK])


def test_load_mcp_config(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fs": {"command": "npx", "args": ["-y", "server-fs", "."]},
                    "off": {"command": "x", "disabled": True},
                }
            }
        ),
        encoding="utf-8",
    )
    cfgs = load_mcp_config(tmp_path)
    names = {c.name for c in cfgs}
    assert names == {"fs", "off"}
    fs = next(c for c in cfgs if c.name == "fs")
    assert fs.command == "npx" and fs.args == ["-y", "server-fs", "."]


def test_manager_start_list_call(tmp_path: Path) -> None:
    async def scenario() -> None:
        mgr = MCPManager([_mock_cfg()], tmp_path)
        try:
            handles = await mgr.start()
            assert len(handles) == 1 and handles[0].ok
            assert [t.name for t in handles[0].tools] == ["echo"]
            assert handles[0].tools[0].qualified == "mock_echo"

            text, is_err = await mgr.call("mock", "echo", {"text": "안녕"})
            assert not is_err and text == "echo: 안녕"

            text, is_err = await mgr.call("mock", "nope", {})
            assert is_err
        finally:
            await mgr.stop()

    run_sync(scenario())


def test_시작실패_서버(tmp_path: Path) -> None:
    async def scenario() -> None:
        mgr = MCPManager(
            [MCPServerConfig(name="bad", command="definitely-not-a-real-binary-xyz")],
            tmp_path,
        )
        handles = await mgr.start()
        assert not handles[0].ok
        await mgr.stop()

    run_sync(scenario())


def test_register_mcp_tools_및_승인(tmp_path: Path) -> None:
    async def scenario() -> None:
        mgr = MCPManager([_mock_cfg()], tmp_path)
        await mgr.start()
        try:
            reg = ToolRegistry()
            assert register_mcp_tools(reg, mgr) == 1
            tool = reg.get("mock_echo")
            assert tool is not None

            auto = ToolContext(
                root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO)
            )
            res = await tool.run({"text": "x"}, auto)
            assert not res.is_error and "echo: x" in res.content

            deny = ToolContext(
                root=tmp_path,
                policy=ApprovalPolicy(
                    mode=ApprovalMode.SUGGEST, approver=lambda _r: False
                ),
            )
            res = await tool.run({"text": "x"}, deny)
            assert res.is_error and "거부" in res.content
        finally:
            await mgr.stop()

    run_sync(scenario())


def test_giga_mcp_list_cli(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"fs": {"command": "npx", "args": ["fs"]}}}),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["mcp", "list", "-C", str(tmp_path)])
    assert result.exit_code == 0 and "fs" in result.stdout

    empty = runner.invoke(app, ["mcp", "list", "-C", str(tmp_path / "none")])
    assert empty.exit_code == 0
    assert "없습니다" in empty.stdout


def test_giga_mcp_check_cli(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"mock": {"command": sys.executable, "args": [_MOCK]}}}
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["mcp", "check", "-C", str(tmp_path)])
    assert result.exit_code == 0
    assert "mock_echo" in result.stdout

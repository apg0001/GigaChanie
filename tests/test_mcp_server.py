"""`giga mcp serve` — GigaChanie 도구를 MCP 로 노출 (자체 클라이언트로 왕복)."""

from __future__ import annotations

import sys
from pathlib import Path

from gigachanie.mcp import MCPManager
from gigachanie.mcp.config import MCPServerConfig


def _cfg(root: Path, *, write: bool = False) -> MCPServerConfig:
    args = ["-m", "gigachanie", "mcp", "serve", "-C", str(root)]
    if write:
        args.append("-w")
    return MCPServerConfig(name="giga", command=sys.executable, args=args)


def test_serve_list_and_read(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("월드", encoding="utf-8")

    async def scenario() -> None:
        mgr = MCPManager([_cfg(tmp_path)], tmp_path)
        try:
            handles = await mgr.start()
            assert handles[0].ok, handles[0].error
            names = {t.name for t in handles[0].tools}
            assert {"read_file", "grep", "glob", "list_dir"} <= names
            assert "write_file" not in names  # 기본은 읽기 전용

            text, is_err = await mgr.call("giga", "read_file", {"path": "hello.txt"})
            assert not is_err and "월드" in text
        finally:
            await mgr.stop()

    from gigachanie.serving.base import run_sync

    run_sync(scenario())


def test_serve_write_모드(tmp_path: Path) -> None:
    async def scenario() -> None:
        mgr = MCPManager([_cfg(tmp_path, write=True)], tmp_path)
        try:
            handles = await mgr.start()
            assert handles[0].ok, handles[0].error
            assert "write_file" in {t.name for t in handles[0].tools}

            text, is_err = await mgr.call(
                "giga", "write_file", {"path": "out.txt", "content": "생성됨"}
            )
            assert not is_err
        finally:
            await mgr.stop()

    from gigachanie.serving.base import run_sync

    run_sync(scenario())
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "생성됨"

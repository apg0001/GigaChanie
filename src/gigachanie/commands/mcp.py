"""`giga mcp` - MCP 서버 설정 확인 및 도구 목록."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from gigachanie.mcp import MCPManager, load_mcp_config
from gigachanie.serving.base import run_sync

console = Console()
app = typer.Typer(name="mcp", help="MCP 서버 설정 / 도구 확인.", no_args_is_help=True)


@app.command("list")
def list_servers(
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """설정된 MCP 서버를 보여준다 (연결하지 않음)."""
    configs = load_mcp_config(root.resolve())
    if not configs:
        console.print(
            "[dim]설정된 MCP 서버가 없습니다.[/dim]\n"
            "[dim]<root>/.mcp.json (Claude Code 호환) 또는 "
            "~/.config/gigachanie/mcp.json 에 mcpServers 를 정의하세요.[/dim]"
        )
        return
    table = Table(title="MCP 서버", expand=True)
    table.add_column("이름", style="bold")
    table.add_column("명령")
    table.add_column("상태")
    for c in configs:
        cmd = " ".join([c.command, *c.args])
        state = "[dim]비활성[/dim]" if c.disabled else "설정됨"
        table.add_row(c.name, cmd, state)
    console.print(table)
    console.print("[dim]실제 연결·도구 확인: [cyan]giga mcp check[/cyan][/dim]")


@app.command("check")
def check(
    root: Path = typer.Option(Path("."), "--root", "-C"),
    server: str = typer.Argument("", help="특정 서버만 확인 (생략 시 전체)."),
) -> None:
    """MCP 서버에 실제로 연결해 도구 목록을 가져온다."""
    configs = load_mcp_config(root.resolve())
    if server:
        configs = [c for c in configs if c.name == server]
    if not configs:
        console.print("[yellow]확인할 서버가 없습니다.[/yellow]")
        raise typer.Exit(code=1)

    manager = MCPManager(configs, root.resolve())

    async def _go() -> int:
        handles = await manager.start()
        try:
            bad = 0
            for h in handles:
                if not h.ok:
                    console.print(f"[red]✗ {h.name}[/red]  {h.error}")
                    bad += 1
                    continue
                console.print(f"[green]✓ {h.name}[/green]  도구 {len(h.tools)}개")
                for t in h.tools:
                    console.print(f"    [cyan]{t.qualified}[/cyan]  {t.description[:80]}")
            return 1 if bad else 0
        finally:
            await manager.stop()

    raise typer.Exit(code=run_sync(_go()))

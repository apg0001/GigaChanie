"""`giga sessions` - 저장된 대화 세션 목록/삭제."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from gigachanie.session import SessionStore

console = Console()
app = typer.Typer(name="sessions", help="대화 세션 목록 / 삭제.", no_args_is_help=True)


def _ago(ts: float) -> str:
    sec = max(0, int(time.time() - ts))
    if sec < 60:
        return f"{sec}초 전"
    if sec < 3600:
        return f"{sec // 60}분 전"
    if sec < 86400:
        return f"{sec // 3600}시간 전"
    return f"{sec // 86400}일 전"


@app.command("list")
def list_sessions(root: Path = typer.Option(Path("."), "--root", "-C")) -> None:
    """이 디렉터리의 대화 세션 (최근 순)."""
    sessions = SessionStore(root.resolve()).list()
    if not sessions:
        console.print("[dim]저장된 세션이 없습니다. `giga chat` 을 하면 자동 저장됩니다.[/dim]")
        return
    table = Table(title="대화 세션", expand=True)
    table.add_column("ID", style="bold")
    table.add_column("턴", justify="right")
    table.add_column("모델")
    table.add_column("수정")
    table.add_column("제목", overflow="fold")
    for i, s in enumerate(sessions):
        mark = " [cyan]← --continue[/cyan]" if i == 0 else ""
        table.add_row(
            s.id + mark, str(s.turns), s.model_id, _ago(s.updated), escape(s.title or "-")
        )
    console.print(table)
    console.print("[dim]이어가기: [cyan]giga chat --resume <ID>[/cyan][/dim]")


@app.command("rm")
def remove(
    session_id: str = typer.Argument(..., help="삭제할 세션 ID."),
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """세션을 삭제한다."""
    if SessionStore(root.resolve()).delete(session_id):
        console.print(f"[green]삭제됨:[/green] {session_id}")
    else:
        console.print(f"[red]'{session_id}' 없음[/red]")
        raise typer.Exit(code=1)

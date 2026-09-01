"""`giga ps` / `giga kill` - 백그라운드 프로세스 조회 및 종료."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from gigachanie.loop.procman import ProcessManager

console = Console()


def ps(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    logs: str = typer.Option("", "--logs", "-l", help="이 id 의 최근 로그를 출력."),
) -> None:
    """agent/chat 이 띄운 백그라운드 프로세스 목록 (죽은 항목은 자동 정리)."""
    pm = ProcessManager(root.resolve())
    if logs:
        console.print(pm.tail(logs, lines=80), markup=False)
        return
    procs = pm.list()
    if not procs:
        console.print("[dim]실행 중인 백그라운드 프로세스가 없습니다.[/dim]")
        return
    table = Table(title="백그라운드 프로세스", expand=True)
    table.add_column("id", style="bold")
    table.add_column("pid", justify="right")
    table.add_column("시작", justify="right")
    table.add_column("명령", overflow="fold")
    for p in procs:
        table.add_row(p.id, str(p.pid), p.started, escape(p.cmd))
    console.print(table)
    console.print("[dim]종료: giga kill <id>  ·  로그: giga ps -l <id>[/dim]")


def kill(
    proc_id: str = typer.Argument(..., help="종료할 프로세스 id (giga ps 로 확인)."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
) -> None:
    """백그라운드 프로세스를 종료한다."""
    if ProcessManager(root.resolve()).stop(proc_id):
        console.print(f"[green]종료됨:[/green] {proc_id}")
    else:
        console.print(f"[red]'{proc_id}' 를 찾을 수 없습니다.[/red]")
        raise typer.Exit(code=1)

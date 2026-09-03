"""`giga undo` - 에이전트의 마지막 편집 턴을 되돌린다."""

from __future__ import annotations

from pathlib import Path

import typer

from gigachanie.loop.checkpoint import CheckpointStore
from gigachanie.ui import make_console

console = make_console()


def undo(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    show_list: bool = typer.Option(
        False, "--list", "-l", help="되돌리지 않고 체크포인트 이력만 표시."
    ),
) -> None:
    """agent/chat 이 마지막 턴에 수정한 파일을 그 이전 상태로 복원한다."""
    store = CheckpointStore(root.resolve())

    if show_list:
        turns = store.history()
        if not turns:
            console.print("[dim]체크포인트가 없습니다.[/dim]")
            return
        for i, t in enumerate(turns):
            marker = "[cyan]← 다음 undo 대상[/cyan]" if i == 0 else ""
            console.print(f"[bold]{t.time}[/bold]  {t.label}  ({len(t.files)}개 파일) {marker}")
        return

    result = store.undo()
    if result is None:
        console.print("[yellow]되돌릴 편집이 없습니다.[/yellow]")
        raise typer.Exit(code=1)
    label, restored = result
    console.print(f"[green]되돌림:[/green] {label}")
    for r in restored:
        console.print(f"  {r}")
    if not restored:
        console.print("  [dim](복원할 파일 없음 - 블롭이 정리되었을 수 있음)[/dim]")

"""`giga prompts` - 재사용 지시문(`.agent/prompts/*.md`) 목록."""

from __future__ import annotations

from pathlib import Path

import typer

from gigachanie.context import list_prompts
from gigachanie.ui import make_console

console = make_console()


def prompts(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    show: str = typer.Option("", "--show", help="이 프롬프트의 본문을 출력."),
) -> None:
    """`agent`/`chat` 의 `-p <이름>` 으로 얹을 수 있는 지시문을 보여준다."""
    found = list_prompts(root.resolve())
    if show:
        p = next((x for x in found if x.name == show), None)
        if p is None:
            console.print(f"[red]없음: {show}[/red]")
            raise typer.Exit(code=1)
        console.print(p.body, markup=False)
        return
    if not found:
        console.print(
            "[dim]재사용 지시문이 없습니다.[/dim]\n"
            "[dim]<root>/.agent/prompts/<이름>.md 또는 "
            "~/.config/gigachanie/prompts/<이름>.md 에 만드세요.[/dim]"
        )
        return
    for p in found:
        first = next((ln for ln in p.body.splitlines() if ln.strip()), "")
        console.print(f"[cyan]{p.name}[/cyan]  [dim]{first[:70]}[/dim]")
    console.print("\n[dim]사용: giga agent -p <이름> \"작업\"  ·  giga chat -p <이름>[/dim]")

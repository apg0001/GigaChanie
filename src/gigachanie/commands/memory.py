"""`giga memory ...` - 장기 메모리 관리 (메모리 하네스 2층)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from gigachanie.context.memory import MemoryStore
from gigachanie.ui import make_console

console = make_console()
app = typer.Typer(name="memory", help="장기 메모리 조회 / 추가 / 삭제.", no_args_is_help=True)


def _store(root: Path) -> MemoryStore:
    return MemoryStore(root.resolve())


@app.command("list")
def list_memories(
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """저장된 메모리 목록."""
    entries = _store(root).all_entries()
    if not entries:
        console.print("[dim]저장된 메모리가 없습니다. `giga memory add` 로 추가하세요.[/dim]")
        return
    table = Table(title="장기 메모리", expand=True)
    table.add_column("slug", style="bold")
    table.add_column("제목")
    table.add_column("태그")
    table.add_column("요약", overflow="fold")
    for e in entries:
        table.add_row(
            e.slug, escape(e.title), escape(", ".join(e.tags)), escape(e.summary)
        )
    console.print(table)


@app.command("show")
def show(
    slug: str = typer.Argument(..., help="메모리 slug."),
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """메모리 본문 출력."""
    entry = _store(root).get(slug)
    if entry is None:
        console.print(f"[red]'{slug}' 없음[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{escape(entry.title)}[/bold]  [dim]({entry.created})[/dim]")
    if entry.tags:
        console.print(f"[dim]태그: {escape(', '.join(entry.tags))}[/dim]")
    console.print()
    console.print(entry.body, markup=False)


@app.command("add")
def add(
    title: str = typer.Argument(..., help="메모리 제목."),
    body: str = typer.Option("", "--body", "-b", help="본문. 생략하면 표준입력에서 읽음."),
    tags: str = typer.Option("", "--tags", "-t", help="쉼표로 구분한 태그."),
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """메모리를 추가한다."""
    text = body or sys.stdin.read().strip()
    if not text:
        console.print("[red]본문이 비어 있습니다.[/red]")
        raise typer.Exit(code=1)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    entry = _store(root).add(title, text, tag_list)
    console.print(f"[green]저장됨:[/green] {entry.slug}  ({entry.path})")


@app.command("search")
def search(
    query: str = typer.Argument(..., help="검색어."),
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """토큰 겹침으로 메모리를 검색한다."""
    hits = _store(root).search(query)
    if not hits:
        console.print(f"[dim]'{query}' 관련 메모리 없음[/dim]")
        return
    for e in hits:
        console.print(f"[bold]{e.slug}[/bold] — {escape(e.title)}")
        console.print(f"  [dim]{escape(e.summary)}[/dim]")


@app.command("rm")
def remove(
    slug: str = typer.Argument(..., help="삭제할 메모리 slug."),
    root: Path = typer.Option(Path("."), "--root", "-C"),
) -> None:
    """메모리를 삭제한다."""
    if _store(root).remove(slug):
        console.print(f"[green]삭제됨:[/green] {slug}")
    else:
        console.print(f"[red]'{slug}' 없음[/red]")
        raise typer.Exit(code=1)

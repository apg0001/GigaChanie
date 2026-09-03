"""`giga ext` - 확장 패키지(커스텀 명령·프롬프트 묶음) 설치/목록/제거."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from gigachanie import extpack
from gigachanie.ui import make_console

console = make_console()
app = typer.Typer(name="ext", help="확장 패키지 설치 / 목록 / 제거.", no_args_is_help=True)


@app.command("install")
def install(
    path: Path = typer.Argument(..., help="giga-ext.yaml 이 있는 디렉터리."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="설치할 프로젝트 루트."),
    force: bool = typer.Option(False, "--force", "-f", help="같은 이름 파일을 덮어쓴다."),
) -> None:
    """패키지의 commands/·prompts/ 파일을 `.agent/` 로 복사한다."""
    try:
        pkg, copied, skipped = extpack.install(root.resolve(), path, force=force)
    except extpack.ExtError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    desc = f" — {pkg.description}" if pkg.description else ""
    console.print(f"[green]설치:[/green] {pkg.name}{desc}")
    for rel in copied:
        console.print(f"  + {rel}")
    for rel in skipped:
        console.print(f"  [yellow]· {rel} (이미 있음, --force 로 덮어쓰기)[/yellow]")
    if not copied and not skipped:
        console.print("[dim]복사할 commands/ · prompts/ 파일이 없습니다.[/dim]")


@app.command("list")
def list_ext(
    root: Path = typer.Option(Path("."), "--root", "-C", help="프로젝트 루트."),
) -> None:
    """설치된 확장 패키지 목록."""
    reg = extpack.installed(root.resolve())
    if not reg:
        console.print("[dim]설치된 확장이 없습니다. `giga ext install <경로>`.[/dim]")
        return
    table = Table(title="설치된 확장", expand=True)
    table.add_column("이름", style="bold")
    table.add_column("설명")
    table.add_column("파일", justify="right")
    for name, e in reg.items():
        table.add_row(name, e.get("description", ""), str(len(e.get("files", []))))
    console.print(table)


@app.command("remove")
def remove(
    name: str = typer.Argument(..., help="제거할 확장 이름."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="프로젝트 루트."),
) -> None:
    """확장이 설치한 파일을 지운다."""
    try:
        removed = extpack.remove(root.resolve(), name)
    except extpack.ExtError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]제거:[/green] {name} ({len(removed)}개 파일)")

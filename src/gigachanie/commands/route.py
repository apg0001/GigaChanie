"""`giga route` - 오케스트레이션 라우팅 결정을 미리 본다 (모델 호출 없음)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from gigachanie.orchestra.router import classify_task, load_orchestra_config

console = Console()


def route(
    task: list[str] = typer.Argument(None, help="분류해볼 작업 문장 (생략 시 설정만 표시)."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
) -> None:
    """orchestra.yaml 설정과, 주어진 작업이 어떤 모델로 라우팅되는지 보여준다."""
    oc = load_orchestra_config(root.resolve())
    if not oc.enabled:
        console.print(
            "[yellow]오케스트레이션이 설정되지 않았습니다.[/yellow]\n"
            "[dim]<root>/.agent/orchestra.yaml 또는 ~/.config/gigachanie/orchestra.yaml "
            "에 models + router 를 정의하세요.[/dim]"
        )
        raise typer.Exit(code=1)

    table = Table(title="모델 슬롯", expand=True)
    table.add_column("이름", style="bold")
    table.add_column("백엔드")
    table.add_column("모델")
    for name, ref in oc.models.items():
        mark = " [cyan](default)[/cyan]" if name == oc.default else ""
        table.add_row(name + mark, ref.backend, ref.model)
    console.print(table)

    if oc.rules:
        console.print("\n[bold]규칙[/bold]")
        for kind, slot in oc.rules.items():
            console.print(f"  {kind}  →  {slot}")

    if task:
        text = " ".join(task)
        kind = classify_task(text)
        routed = oc.route(kind)
        console.print()
        console.print(
            f"[bold]작업 분류:[/bold] [cyan]{kind.value}[/cyan]  →  "
            f"[green]{routed.model if routed else '(모델 없음)'}[/green]"
            + (f" ([dim]{routed.backend}[/dim])" if routed else "")
        )

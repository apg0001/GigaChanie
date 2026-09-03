"""`giga ensemble` - 여러 모델에게 같은 질문을 던지고 종합한다."""

from __future__ import annotations

from pathlib import Path

import typer

from gigachanie.context import expand_refs
from gigachanie.orchestra.ensemble import run_ensemble
from gigachanie.orchestra.multi import default_specs, resolve_backend
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.ui import make_console

console = make_console()


def ensemble(
    question: list[str] = typer.Argument(..., help="여러 모델에게 물어볼 질문."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트 (@참조·orchestra.yaml)."),
    models: list[str] = typer.Option(
        [], "--model", "-m", help="모델 ID 또는 orchestra.yaml 슬롯 (반복). 생략 시 슬롯 전체."
    ),
    judge: str = typer.Option(
        "", "--judge", "-j", help="종합할 판정 모델 (생략 시 첫 번째 모델)."
    ),
) -> None:
    """N개 모델을 병렬로 돌리고 판정 모델이 하나의 답으로 종합한다 (도구 미사용)."""
    root = root.resolve()
    specs = models or default_specs(root)
    if len(specs) < 2:
        console.print(
            "[yellow]앙상블에는 모델이 2개 이상 필요합니다.[/yellow] "
            "`-m <ID> -m <ID>` 또는 `.agent/orchestra.yaml` 의 models 를 채우세요."
        )
        raise typer.Exit(code=2)

    prompt = expand_refs(" ".join(question), root).text
    try:
        members = [resolve_backend(s, root) for s in specs]
        judge_pair = resolve_backend(judge, root) if judge else members[0]
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(
        f"[dim]모델 {', '.join(label for label, _ in members)} · "
        f"판정 {judge_pair[0]}[/dim]\n"
    )
    result = run_sync(run_ensemble(prompt, members, judge_pair))

    for label, ans in result.answers:
        console.rule(f"[dim]{label}[/dim]")
        console.print(ans, markup=False)
    console.print()
    console.rule("[bold]종합[/bold]")
    console.print(result.verdict, markup=False)

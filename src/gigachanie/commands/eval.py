"""`giga eval` - 태스크셋으로 에이전트 성능을 측정한다."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import typer
from rich.table import Table

from gigachanie.eval.harness import EvalReport, load_tasks, run_task
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.ui import make_console

console = make_console()


def _bundled_tasks_dir() -> Path:
    return Path(str(resources.files("gigachanie.eval").joinpath("tasks")))


def eval_cmd(
    tasks_dir: Path = typer.Option(
        None, "--tasks", "-T", help="태스크 디렉터리 (기본: 내장 태스크셋)."
    ),
    only: list[str] = typer.Option(
        None, "--task", "-t", help="특정 태스크만 실행 (반복 지정 가능)."
    ),
    as_json: bool = typer.Option(False, "--json", help="결과를 JSON 으로 출력."),
) -> None:
    """선택된 모델로 태스크셋을 실행하고 통과율을 리포트한다."""
    tdir = tasks_dir or _bundled_tasks_dir()
    if not tdir.is_dir():
        console.print(f"[red]태스크 디렉터리 없음: {tdir}[/red]")
        raise typer.Exit(code=1)

    tasks = load_tasks(tdir, list(only) if only else None)
    if not tasks:
        console.print("[yellow]실행할 태스크가 없습니다.[/yellow]")
        raise typer.Exit(code=1)

    try:
        backend = build_backend()
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(
        f"[dim]모델 {backend.model} · 태스크 {len(tasks)}개 · 루트 {tdir}[/dim]\n"
    )

    async def _go() -> EvalReport:
        report = EvalReport(model=backend.model)
        try:
            for task in tasks:
                console.print(f"[bold]▶ {task.name}[/bold] …")
                result = await run_task(task, backend)
                report.results.append(result)
                mark = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
                extra = f" ({result.error})" if result.error else ""
                console.print(
                    f"  {mark}  스텝 {result.steps} · 토큰 {result.total_tokens} · "
                    f"편집실패 {result.edit_failures} · {result.seconds}s{extra}"
                )
                for cr in result.checks:
                    if not cr.passed:
                        console.print(f"    [red]✗[/red] {cr.check.type}: {cr.detail}")
        finally:
            await backend.close()
        return report

    report = run_sync(_go())

    if as_json:
        console.print_json(
            json.dumps(
                {
                    "model": report.model,
                    "pass_rate": round(report.pass_rate, 3),
                    "passed": report.passed,
                    "total": report.total,
                    "results": [
                        {
                            "task": r.task,
                            "passed": r.passed,
                            "steps": r.steps,
                            "tokens": r.total_tokens,
                            "edit_failures": r.edit_failures,
                            "stop_reason": r.stop_reason,
                            "seconds": r.seconds,
                            "error": r.error,
                        }
                        for r in report.results
                    ],
                },
                ensure_ascii=False,
            )
        )
    else:
        table = Table(title="평가 결과", expand=True)
        table.add_column("태스크", style="bold")
        table.add_column("결과")
        table.add_column("스텝", justify="right")
        table.add_column("토큰", justify="right")
        table.add_column("편집실패", justify="right")
        table.add_column("시간(s)", justify="right")
        for r in report.results:
            table.add_row(
                r.task,
                "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]",
                str(r.steps),
                str(r.total_tokens),
                str(r.edit_failures),
                str(r.seconds),
            )
        console.print()
        console.print(table)
        console.print(
            f"\n[bold]통과율 {report.passed}/{report.total} "
            f"({report.pass_rate:.0%})[/bold] · 총 편집실패 {report.total_edit_failures}"
        )

    raise typer.Exit(code=0 if report.passed == report.total else 1)

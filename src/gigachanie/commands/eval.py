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
    root: Path = typer.Option(
        Path("."), "--root", "-C", help="회귀 비교 히스토리를 저장할 프로젝트 루트."
    ),
    no_history: bool = typer.Option(
        False, "--no-history", help="통과율 히스토리 기록·비교를 하지 않는다."
    ),
) -> None:
    """선택된 모델로 태스크셋을 실행하고 통과율을 리포트한다.

    직전 실행 대비 같은 모델의 통과율이 떨어지면 종료코드 2 (회귀 게이트).
    """
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

    regressed = False
    if not no_history:
        prev = _load_last_rate(root.resolve(), backend.model)
        _append_history(root.resolve(), backend.model, report)
        if prev is not None and report.pass_rate + 1e-9 < prev:
            regressed = True
            if not as_json:
                console.print(
                    f"[red]회귀:[/red] 통과율 {prev:.0%} → {report.pass_rate:.0%} "
                    f"(직전 대비 하락)"
                )
        elif prev is not None and not as_json:
            arrow = "→" if report.pass_rate == prev else "↑"
            console.print(f"[dim]직전 통과율 {prev:.0%} {arrow} {report.pass_rate:.0%}[/dim]")

    if regressed:
        raise typer.Exit(code=2)
    raise typer.Exit(code=0 if report.passed == report.total else 1)


_HISTORY = Path(".agent") / "eval-history.jsonl"


def _append_history(root: Path, model: str, report: EvalReport) -> None:
    import time

    path = root / _HISTORY
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "model": model,
                        "pass_rate": round(report.pass_rate, 4),
                        "passed": report.passed,
                        "total": report.total,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass


def _load_last_rate(root: Path, model: str) -> float | None:
    path = root / _HISTORY
    if not path.is_file():
        return None
    last: float | None = None
    for line in path.read_text("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("model") == model and "pass_rate" in row:
            last = float(row["pass_rate"])
    return last

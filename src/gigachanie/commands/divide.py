"""`giga divide` - 플래너가 작업을 쪼개고, 하위 작업을 순차로 실행한다."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from gigachanie.context import expand_refs
from gigachanie.orchestra.divide import plan_subtasks
from gigachanie.orchestra.multi import resolve_backend
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.ui import make_console

console = make_console()


def divide(
    goal: list[str] = typer.Argument(..., help="쪼갤 전체 목표."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    planner: str = typer.Option("", "--planner", help="분할에 쓸 모델 (생략 시 기본 모델)."),
    write: bool = typer.Option(
        False, "--write", "-w", help="하위 작업이 파일을 수정하도록 허용."
    ),
    mode: str = typer.Option("auto-edit", "--mode", help="하위 작업 승인 모드."),
    yes: bool = typer.Option(False, "--yes", "-y", help="분할 확인 없이 바로 실행."),
    dry_run: bool = typer.Option(False, "--dry-run", help="분할만 하고 실행하지 않음."),
) -> None:
    """플래너 모델이 목표를 3~6개 하위 작업으로 나누고 순차로 `giga agent` 실행."""
    root = root.resolve()
    goal_text = expand_refs(" ".join(goal), root).text

    try:
        pbackend = (
            resolve_backend(planner, root)[1] if planner else build_backend(root=root)
        )
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    async def _plan() -> list[str]:
        try:
            return await plan_subtasks(pbackend, goal_text)
        finally:
            await pbackend.close()

    subtasks = run_sync(_plan())
    if not subtasks:
        console.print("[yellow]하위 작업을 만들지 못했습니다.[/yellow]")
        raise typer.Exit(code=1)

    console.rule("[bold]분할[/bold]")
    for i, st in enumerate(subtasks, 1):
        console.print(f"  {i}. {st}")

    if dry_run:
        return
    if not yes:
        if not sys.stdin.isatty():
            console.print(
                "[yellow]비대화 환경입니다. 실행하려면 -y 를 주세요 "
                "(--dry-run 으로 미리보기).[/yellow]"
            )
            raise typer.Exit(code=0)
        if not typer.confirm("\n이 순서로 실행할까요?", default=False):
            raise typer.Exit(code=0)

    failed = 0
    for i, st in enumerate(subtasks, 1):
        console.rule(f"[bold]{i}/{len(subtasks)}[/bold]  {st}")
        argv = [sys.executable, "-m", "gigachanie", "agent", "-C", str(root)]
        if write:
            argv += ["-w", "--mode", mode]
        argv.append(
            f"전체 목표: {goal_text}\n\n지금 할 하위 작업: {st}\n"
            f"(이 하위 작업만 수행하고, 나머지는 다른 단계에서 처리한다)"
        )
        rc = subprocess.run(argv, check=False).returncode
        if rc != 0:
            failed += 1
            console.print(f"[yellow]하위 작업 {i} 종료코드 {rc}[/yellow]")

    console.rule("[bold]완료[/bold]")
    console.print(f"{len(subtasks) - failed}/{len(subtasks)} 하위 작업 성공")
    raise typer.Exit(code=1 if failed else 0)

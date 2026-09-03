"""`giga plan` - 파일을 건드리지 않고 실행 계획만 세운다 (원하면 승인 후 실행)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from gigachanie.commands._agentui import make_event_printer
from gigachanie.commands._pick import is_tty
from gigachanie.context import (
    MemoryStore,
    build_repo_map,
    expand_refs,
    load_project_context,
)
from gigachanie.loop.agent import Agent
from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.prompt import PLAN_MODE_PROMPT, build_system_prompt
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.ui import make_console

console = make_console()


def plan(
    task: list[str] = typer.Argument(..., help="계획을 세울 작업."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    execute: bool = typer.Option(
        False, "--execute", "-x", help="계획 확인 후 곧바로 실행한다 (giga agent -w)."
    ),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
    max_steps: int = typer.Option(15, "--max-steps"),
    no_context: bool = typer.Option(False, "--no-context"),
    no_map: bool = typer.Option(False, "--no-map"),
) -> None:
    """읽기 도구만으로 코드베이스를 조사해 단계별 실행 계획을 출력한다."""
    root = root.resolve()
    if not root.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    task_text = " ".join(task)
    try:
        backend = build_backend(root=root)
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    exp = expand_refs(task_text, root)
    pc = None if no_context else load_project_context(root, root)
    rm = None if no_map else build_repo_map(root, cwd=root)
    mem = "" if no_context else MemoryStore(root).index_text()

    sys_prompt = build_system_prompt(
        extra=PLAN_MODE_PROMPT,
        project_context=pc.text if pc and pc.found else None,
        repo_map=rm.text if rm and rm.found else None,
        memory_index=mem or None,
    )
    agent = Agent(
        backend,
        default_readonly_registry(),
        ToolContext(root=root),
        system_prompt=sys_prompt,
        max_steps=max_steps,
        temperature=temperature,
    )

    console.print(f"[dim]모델 {getattr(backend, 'model', '?')} · 계획 모드 · 루트 {root}[/dim]")

    async def _go() -> str:
        try:
            result = await agent.run(exp.text, on_event=make_event_printer(), images=exp.images)
        finally:
            await backend.close()
        return result.final_text

    plan_text = run_sync(_go())
    console.print()
    console.rule("[bold]계획[/bold]")
    console.print(plan_text or "(빈 응답)", markup=False)

    if not execute:
        console.print("\n[dim]실행하려면: giga plan -x \"…\"  또는  giga agent -w \"…\"[/dim]")
        return

    if not is_tty():
        console.print(
            "\n[yellow]비대화 환경입니다. 계획대로 실행하려면 대화형으로 "
            "`giga plan -x` 를 쓰거나 `giga agent -w` 로 직접 실행하세요.[/yellow]"
        )
        raise typer.Exit(code=0)
    if not typer.confirm("\n이 계획대로 실행할까요?", default=False):
        raise typer.Exit(code=0)

    handoff = (
        "아래 계획에 따라 작업을 수행하세요. 필요하면 계획을 조정하되 "
        "목표는 그대로입니다.\n\n"
        f"[원래 요청]\n{task_text}\n\n[계획]\n{plan_text}"
    )
    argv = [
        sys.executable,
        "-m",
        "gigachanie",
        "agent",
        "-C",
        str(root),
        "-w",
        "--mode",
        "auto-edit",
        handoff,
    ]
    console.print("\n[dim]$ giga agent -w --mode auto-edit …[/dim]\n")
    raise typer.Exit(code=subprocess.run(argv, check=False).returncode)

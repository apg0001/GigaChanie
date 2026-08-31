"""`giga agent` - 에이전트 루프를 한 번 실행한다.

읽기 도구는 항상, 쓰기/실행 도구는 --write 로 활성화한다.
승인 모드는 --mode (suggest | auto-edit | full-auto), --yolo 는 full-auto + write 단축.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from gigachanie.commands._agentui import interactive_approver, make_event_printer
from gigachanie.loop.agent import Agent
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend

console = Console()


def agent(
    task: list[str] = typer.Argument(..., help="에이전트에게 시킬 작업."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트 디렉터리."),
    write: bool = typer.Option(
        False, "--write", "-w", help="쓰기/실행 도구(write_file, run_shell) 활성화."
    ),
    mode: str = typer.Option(
        "suggest", "--mode", help="승인 모드: suggest | auto-edit | full-auto."
    ),
    yolo: bool = typer.Option(
        False, "--yolo", help="full-auto + write. 확인 없이 전부 실행(주의)."
    ),
    max_steps: int = typer.Option(20, "--max-steps", help="최대 반복 스텝."),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
) -> None:
    """도구를 사용해 코드베이스를 조사하거나 수정한다."""
    task_text = " ".join(task)
    try:
        approval_mode = ApprovalMode.parse("full-auto" if yolo else mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    writable = write or yolo
    try:
        backend = build_backend()
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    tools = build_registry(writable=writable)
    policy = ApprovalPolicy(
        mode=approval_mode,
        approver=None if yolo else interactive_approver,
    )
    ctx = ToolContext(root=root.resolve(), policy=policy)
    if not ctx.root.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[dim]모델 {backend.model} · 도구 {', '.join(tools.names())} · "
        f"모드 {approval_mode.value}{' · yolo' if yolo else ''} · 루트 {ctx.root}[/dim]"
    )
    handler = make_event_printer()
    ag = Agent(backend, tools, ctx, max_steps=max_steps, temperature=temperature)

    async def _go() -> int:
        try:
            result = await ag.run(task_text, on_event=handler)
        finally:
            await backend.close()
        console.print()
        console.rule("[bold]결과[/bold]")
        console.print(result.final_text or "(빈 응답)", markup=False)
        console.print(
            f"[dim]스텝 {result.steps} · 종료 {result.stop_reason} · "
            f"토큰 {result.usage.total_tokens}[/dim]"
        )
        return 0 if result.ok else 1

    raise typer.Exit(code=run_sync(_go()))

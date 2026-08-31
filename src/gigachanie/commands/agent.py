"""`giga agent` - 에이전트 루프를 한 번 실행한다 (읽기 전용 도구).

대화형 REPL 은 이슈 #8, 파일 수정/셸 도구는 이후 이슈에서 추가된다.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from gigachanie.loop.agent import Agent, AgentEvent
from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend

console = Console()


def _make_printer() -> tuple[object, list[str]]:
    state = {"streaming": False}

    def handle(ev: AgentEvent) -> None:
        if ev.kind == "step":
            if ev.step > 1:
                console.print()
            console.rule(f"[dim]step {ev.step}[/dim]", style="dim")
        elif ev.kind == "assistant_delta":
            console.print(ev.text, end="", markup=False, soft_wrap=True)
            state["streaming"] = True
        elif ev.kind == "assistant_text":
            if state["streaming"]:
                console.print()
                state["streaming"] = False
        elif ev.kind == "tool_call":
            args = ", ".join(f"{k}={v!r}" for k, v in ev.tool_args.items())
            console.print(f"[cyan]→ {ev.tool_name}[/cyan]({args})")
        elif ev.kind == "tool_result":
            style = "red" if ev.is_error else "green"
            preview = ev.text if len(ev.text) <= 600 else ev.text[:600] + " …"
            console.print(f"[{style}]{preview}[/{style}]", markup=False, soft_wrap=True)
        elif ev.kind == "error":
            console.print(f"[red]오류: {ev.text}[/red]")

    return handle, []


def agent(
    task: list[str] = typer.Argument(..., help="에이전트에게 시킬 작업."),
    root: Path = typer.Option(
        Path("."), "--root", "-C", help="작업 루트 디렉터리."
    ),
    max_steps: int = typer.Option(20, "--max-steps", help="최대 반복 스텝."),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
) -> None:
    """읽기 전용 도구로 코드베이스 질문에 답하거나 조사한다."""
    task_text = " ".join(task)
    try:
        backend = build_backend()
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    tools = default_readonly_registry()
    ctx = ToolContext(root=root.resolve())
    if not ctx.root.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[dim]모델 {backend.model} · 도구 {', '.join(tools.names())} · 루트 {ctx.root}[/dim]"
    )
    handler, _ = _make_printer()
    ag = Agent(
        backend, tools, ctx, max_steps=max_steps, temperature=temperature
    )

    async def _go() -> int:
        try:
            result = await ag.run(task_text, on_event=handler)  # type: ignore[arg-type]
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

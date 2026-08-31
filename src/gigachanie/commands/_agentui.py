"""`giga agent` / `giga chat` 공용 렌더링 · 승인 UI."""

from __future__ import annotations

from collections.abc import Callable

import typer
from rich.console import Console
from rich.syntax import Syntax

from gigachanie.loop.agent import AgentEvent
from gigachanie.loop.approval import ApprovalRequest

console = Console()


def interactive_approver(req: ApprovalRequest) -> bool:
    console.print()
    console.print(f"[yellow bold]승인 요청[/yellow bold] · {req.summary}")
    if req.detail:
        lexer = "diff" if req.kind == "write" else "bash"
        console.print(
            Syntax(req.detail[:4000], lexer, theme="ansi_dark", word_wrap=True)
        )
    return typer.confirm("실행할까요?", default=False)


def make_event_printer() -> Callable[[AgentEvent], None]:
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
            preview = ev.text if len(ev.text) <= 800 else ev.text[:800] + " …"
            console.print(f"[{style}]{preview}[/{style}]", markup=False, soft_wrap=True)
        elif ev.kind == "error":
            console.print(f"[red]오류: {ev.text}[/red]")

    return handle

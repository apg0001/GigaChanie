"""`giga agent` / `giga chat` 공용 렌더링 · 승인 UI."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
import yaml
from rich.syntax import Syntax

from gigachanie.loop.agent import AgentEvent
from gigachanie.loop.approval import ApprovalRequest, Approver
from gigachanie.ui import make_console

console = make_console()


def _remember_rule(root: Path, req: ApprovalRequest) -> None:
    """'항상 허용' 선택 시 프로젝트 permissions.yaml 에 규칙을 추가한다."""
    pf = root / ".agent" / "permissions.yaml"
    pf.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = yaml.safe_load(pf.read_text("utf-8")) if pf.is_file() else {}
    except (OSError, yaml.YAMLError):
        data = {}
    data = data or {}

    if req.kind in ("write", "delete") and req.path:
        rel = req.path.replace("\\", "/")
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        rule = f"{parent}/**" if parent else rel
        added = data.setdefault("allow_paths", [])
        target, kind = added, "allow_paths"
    else:
        raw = (req.detail or req.summary).strip()
        first = raw.split()[0] if raw else ""
        rule = f"^{first}\\b" if first else ""
        added = data.setdefault("allow_shell", [])
        target, kind = added, "allow_shell"

    if rule and rule not in target:
        target.append(rule)
        pf.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")
        console.print(f"[dim]규칙 추가: {kind} += {rule}  ({pf})[/dim]")


def make_approver(root: Path) -> Approver:
    def approve(req: ApprovalRequest) -> bool:
        console.print()
        console.print(f"[yellow bold]승인 요청[/yellow bold] · {req.summary}")
        if req.detail:
            lexer = "diff" if req.kind == "write" else "bash"
            console.print(
                Syntax(req.detail[:4000], lexer, theme="ansi_dark", word_wrap=True)
            )
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return typer.confirm("실행할까요?", default=False)

        choice = typer.prompt(
            "[y] 실행  [n] 건너뛰기  [a] 항상 허용",
            default="n",
            show_default=False,
        ).strip().lower()
        if choice in ("a", "always"):
            _remember_rule(root, req)
            return True
        return choice in ("y", "yes")

    return approve


def interactive_approver(req: ApprovalRequest) -> bool:
    """root 없이 쓰는 단순 승인 (테스트/폴백용)."""
    return make_approver(Path.cwd())(req)


def ask_user(question: str, options: list[str], allow_custom: bool) -> str:
    """에이전트가 ask_user 도구를 호출했을 때 사용자에게 묻는다."""
    console.print()
    console.print(f"[bold cyan]에이전트가 묻습니다:[/bold cyan] {question}")
    for i, opt in enumerate(options, start=1):
        console.print(f"  [cyan]{i}[/cyan]. {opt}")
    if allow_custom:
        console.print("  [dim]또는 자유롭게 입력하세요.[/dim]")

    hint = "번호 또는 직접 입력" if options else "답변"
    try:
        raw = str(typer.prompt(hint, default="", show_default=False)).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if options and raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw


def _print_tasks(text: str) -> None:
    console.print("[bold]할 일[/bold]")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[x]"):
            console.print(f"  [green]✔[/green] [dim]{s[3:].strip()}[/dim]")
        elif s.startswith("[~]"):
            console.print(f"  [yellow]▶[/yellow] {s[3:].strip()}")
        elif s.startswith("[ ]"):
            console.print(f"  [dim]○[/dim] {s[3:].strip()}")
        elif s.startswith("—"):
            console.print(f"  [dim]{s}[/dim]")


class _Printer:
    """이벤트 프린터. `.answered` 로 이번 실행의 최종 답변을 이미 출력했는지 알 수 있다."""

    def __init__(self) -> None:
        self._streaming = False
        self.answered = False

    def __call__(self, ev: AgentEvent) -> None:
        self.handle(ev)

    def handle(self, ev: AgentEvent) -> None:
        if ev.kind == "step":
            if ev.step > 1:
                console.print()
            self.answered = False
            console.rule(f"[dim]step {ev.step}[/dim]", style="dim")
        elif ev.kind == "assistant_delta":
            console.print(ev.text, end="", markup=False, soft_wrap=True)
            self._streaming = True
            self.answered = True
        elif ev.kind == "assistant_text":
            if self._streaming:
                console.print()
                self._streaming = False
            elif ev.text.strip():
                console.print(ev.text, markup=False, soft_wrap=True)
                self.answered = True
        elif ev.kind == "tool_call":
            if ev.tool_name == "update_tasks":
                return
            args = ", ".join(f"{k}={v!r}" for k, v in ev.tool_args.items())
            console.print(f"[cyan]→ {ev.tool_name}[/cyan]({args})")
        elif ev.kind == "tool_result":
            if ev.tool_name == "update_tasks" and not ev.is_error:
                _print_tasks(ev.text)
                return
            style = "red" if ev.is_error else "green"
            preview = ev.text if len(ev.text) <= 800 else ev.text[:800] + " …"
            console.print(f"[{style}]{preview}[/{style}]", markup=False, soft_wrap=True)
        elif ev.kind == "compact":
            console.print(f"[dim]↯ {ev.text}[/dim]")
        elif ev.kind == "error":
            console.print(f"[red]오류: {ev.text}[/red]")


def make_event_printer() -> _Printer:
    return _Printer()

"""`giga chat` - 대화형 에이전트 REPL.

한 세션 동안 대화 맥락을 유지하며, 슬래시 명령으로 모델/모드/도구를 조절한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from platformdirs import user_config_path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from gigachanie.commands._agentui import interactive_approver, make_event_printer
from gigachanie.config import load_config
from gigachanie.loop.agent import Agent
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import Backend, BackendError, run_sync
from gigachanie.serving.factory import build_backend

console = Console()

_HELP = """\
슬래시 명령:
  /help              이 도움말
  /tools             등록된 도구 목록
  /model [ID]        현재 모델 표시 / 변경
  /mode <모드>       승인 모드: suggest | auto-edit | full-auto
  /write on|off      쓰기·실행 도구 토글
  /clear             대화 맥락 초기화 (모델·설정 유지)
  /steps <N>         최대 스텝 변경
  /info              현재 세션 상태
  /exit, /quit       종료
빈 줄 입력은 무시됩니다. 종료는 /exit 또는 Ctrl-D.
"""


class ChatSession:
    def __init__(
        self,
        backend: Backend,
        root: Path,
        *,
        mode: ApprovalMode,
        writable: bool,
        max_steps: int,
        temperature: float,
    ) -> None:
        self.backend = backend
        self.root = root
        self.mode = mode
        self.writable = writable
        self.max_steps = max_steps
        self.temperature = temperature
        self.agent = self._new_agent()

    def _new_agent(self) -> Agent:
        tools = build_registry(writable=self.writable)
        policy = ApprovalPolicy(mode=self.mode, approver=interactive_approver)
        ctx = ToolContext(root=self.root, policy=policy)
        return Agent(
            self.backend,
            tools,
            ctx,
            max_steps=self.max_steps,
            temperature=self.temperature,
        )

    def rebuild(self, *, keep_history: bool = True) -> None:
        old = self.agent
        self.agent = self._new_agent()
        if keep_history:
            # 시스템 프롬프트(0번) 제외한 대화만 이어받기
            self.agent.messages = [self.agent.messages[0], *old.messages[1:]]

    # --------------------------------------------------------------- 슬래시

    def handle_slash(self, line: str) -> bool:
        """슬래시 명령 처리. 세션을 계속하면 True, 종료면 False."""
        parts = line.strip().split()
        cmd, args = parts[0], parts[1:]

        if cmd in ("/exit", "/quit", "/q"):
            return False
        if cmd == "/help":
            console.print(_HELP)
        elif cmd == "/tools":
            console.print(", ".join(self.agent.tools.names()) or "(없음)")
        elif cmd == "/info":
            self._print_info()
        elif cmd == "/clear":
            self.rebuild(keep_history=False)
            console.print("[dim]대화 맥락을 초기화했습니다.[/dim]")
        elif cmd == "/model":
            self._cmd_model(args)
        elif cmd == "/mode":
            self._cmd_mode(args)
        elif cmd == "/write":
            self._cmd_write(args)
        elif cmd == "/steps":
            self._cmd_steps(args)
        else:
            console.print(f"[yellow]알 수 없는 명령: {cmd}[/yellow] (/help)")
        return True

    def _print_info(self) -> None:
        turns = sum(1 for m in self.agent.messages if m.role == "user")
        console.print(
            f"모델 [cyan]{self.backend.model}[/cyan] · 모드 [cyan]{self.mode.value}[/cyan] · "
            f"쓰기 [cyan]{'on' if self.writable else 'off'}[/cyan] · "
            f"스텝 {self.max_steps} · 턴 {turns} · 루트 {self.root}"
        )

    def _cmd_model(self, args: list[str]) -> None:
        if not args:
            console.print(f"현재 모델: [cyan]{self.backend.model}[/cyan]")
            return
        cfg = load_config().merged(model_id=args[0])
        try:
            new_backend = build_backend(cfg)
        except BackendError as exc:
            console.print(f"[red]{exc}[/red]")
            return
        run_sync(self.backend.close())
        self.backend = new_backend
        self.rebuild(keep_history=True)
        console.print(f"모델 변경: [cyan]{new_backend.model}[/cyan]")

    def _cmd_mode(self, args: list[str]) -> None:
        if not args:
            console.print(f"현재 모드: [cyan]{self.mode.value}[/cyan]")
            return
        try:
            self.mode = ApprovalMode.parse(args[0])
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return
        self.rebuild(keep_history=True)
        console.print(f"승인 모드: [cyan]{self.mode.value}[/cyan]")

    def _cmd_write(self, args: list[str]) -> None:
        if not args or args[0] not in ("on", "off"):
            console.print("사용법: /write on|off")
            return
        self.writable = args[0] == "on"
        self.rebuild(keep_history=True)
        console.print(f"쓰기 도구: [cyan]{'on' if self.writable else 'off'}[/cyan]")

    def _cmd_steps(self, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            console.print("사용법: /steps <N>")
            return
        self.max_steps = max(1, int(args[0]))
        self.agent.max_steps = self.max_steps
        console.print(f"최대 스텝: {self.max_steps}")


async def _run_turn(session: ChatSession, text: str) -> None:
    printer = make_event_printer()
    try:
        result = await session.agent.run(text, on_event=printer)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]중단됨[/yellow]")
        return
    console.print()
    console.rule("[bold]답변[/bold]")
    console.print(result.final_text or "(빈 응답)", markup=False)
    console.print(
        f"[dim]스텝 {result.steps} · {result.stop_reason} · 토큰 {result.usage.total_tokens}[/dim]"
    )


def chat(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트 디렉터리."),
    write: bool = typer.Option(False, "--write", "-w", help="쓰기/실행 도구 활성화."),
    mode: str = typer.Option("suggest", "--mode", help="suggest | auto-edit | full-auto."),
    max_steps: int = typer.Option(20, "--max-steps"),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
) -> None:
    """대화형으로 에이전트와 작업한다."""
    try:
        approval_mode = ApprovalMode.parse(mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    root_path = root.resolve()
    if not root_path.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    try:
        backend = build_backend()
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    session = ChatSession(
        backend,
        root_path,
        mode=approval_mode,
        writable=write,
        max_steps=max_steps,
        temperature=temperature,
    )

    hist_path = user_config_path("gigachanie", appauthor=False, ensure_exists=True) / "chat_history"
    pt: PromptSession[str] = PromptSession(history=FileHistory(str(hist_path)))

    console.print("[bold]GigaChanie chat[/bold] · /help 로 명령 확인, /exit 로 종료")
    session._print_info()

    async def _loop() -> None:
        try:
            while True:
                try:
                    line = await pt.prompt_async("\n› ")
                except (EOFError, KeyboardInterrupt):
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith("/"):
                    if not session.handle_slash(line):
                        break
                    continue
                await _run_turn(session, line)
        finally:
            await session.backend.close()

    run_sync(_loop())
    console.print("[dim]종료합니다.[/dim]")

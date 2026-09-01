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
from rich.markup import escape

from gigachanie.commands._agentui import make_approver, make_event_printer
from gigachanie.config import load_config
from gigachanie.context import (
    MemoryStore,
    build_repo_map,
    expand_file_refs,
    load_project_context,
)
from gigachanie.loop.agent import Agent
from gigachanie.loop.approval import ApprovalMode, build_policy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.checkpoint import CheckpointStore
from gigachanie.loop.procman import ProcessManager
from gigachanie.loop.tools import ToolContext
from gigachanie.permissions import load_permissions
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
  /web on|off        웹 도구(web_search, web_fetch) 토글
  /remember <내용>   장기 메모리에 저장 (제목은 앞 40자)
  /memory            장기 메모리 목록
  /compact           지금까지 대화를 요약해 압축
  /undo              마지막 편집 턴을 되돌림
  /ps                실행 중인 백그라운드 프로세스 목록
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
        use_context: bool = True,
        use_map: bool = True,
        web: bool = False,
    ) -> None:
        self.backend = backend
        self.root = root
        self.mode = mode
        self.writable = writable
        self.web = web
        self.max_steps = max_steps
        self.temperature = temperature
        self.use_context = use_context
        pc = load_project_context(root, root) if use_context else None
        self.project_context = pc.text if pc and pc.found else None
        self.context_sources = [p.name for p in pc.sources] if pc else []
        rm = build_repo_map(root, cwd=root) if use_map else None
        self.repo_map = rm.text if rm and rm.found else None
        self.map_files = len(rm.entries) if rm else 0
        self.memory_store = MemoryStore(root)
        self._refresh_memory()
        self.compact_at = int((load_config().context or 32000) * 0.7)
        self.checkpoints = CheckpointStore(root)
        self.procman = ProcessManager(root)
        self.perms = load_permissions(root)
        self.agent = self._new_agent()

    def _refresh_memory(self) -> None:
        idx = self.memory_store.index_text() if self.use_context else ""
        self.memory_index = idx or None

    def _new_agent(self) -> Agent:
        tools = build_registry(writable=self.writable, web=self.web)
        policy = build_policy(
            self.mode,
            make_approver(self.root),
            extra_allow_shell=self.perms.allow_shell,
            extra_deny_shell=self.perms.deny_shell,
            allow_paths=self.perms.allow_paths,
            deny_paths=self.perms.effective_deny_paths(),
        )
        ctx = ToolContext(
            root=self.root,
            policy=policy,
            checkpoints=self.checkpoints if self.writable else None,
            procman=self.procman if self.writable else None,
        )
        return Agent(
            self.backend,
            tools,
            ctx,
            project_context=self.project_context,
            repo_map=self.repo_map,
            memory_index=self.memory_index,
            max_steps=self.max_steps,
            temperature=self.temperature,
            compact_at=self.compact_at,
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
        elif cmd == "/web":
            self._cmd_web(args)
        elif cmd == "/remember":
            self._cmd_remember(args)
        elif cmd == "/memory":
            self._cmd_memory()
        elif cmd == "/compact":
            self._cmd_compact()
        elif cmd == "/undo":
            self._cmd_undo()
        elif cmd == "/ps":
            self._cmd_ps()
        elif cmd == "/steps":
            self._cmd_steps(args)
        else:
            console.print(f"[yellow]알 수 없는 명령: {cmd}[/yellow] (/help)")
        return True

    def _print_info(self) -> None:
        turns = sum(1 for m in self.agent.messages if m.role == "user")
        ctx_line = ", ".join(self.context_sources) if self.context_sources else "없음"
        map_line = f"{self.map_files}파일" if self.repo_map else "off"
        console.print(
            f"모델 [cyan]{self.backend.model}[/cyan] · 모드 [cyan]{self.mode.value}[/cyan] · "
            f"쓰기 [cyan]{'on' if self.writable else 'off'}[/cyan] · "
            f"스텝 {self.max_steps} · 턴 {turns} · 컨텍스트 {ctx_line} · 맵 {map_line} · "
            f"루트 {self.root}"
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

    def _cmd_web(self, args: list[str]) -> None:
        if not args or args[0] not in ("on", "off"):
            console.print("사용법: /web on|off")
            return
        self.web = args[0] == "on"
        self.rebuild(keep_history=True)
        console.print(f"웹 도구: [cyan]{'on' if self.web else 'off'}[/cyan]")

    def _cmd_remember(self, args: list[str]) -> None:
        text = " ".join(args).strip()
        if not text:
            console.print("사용법: /remember <기억할 내용>")
            return
        title = text[:40] + ("…" if len(text) > 40 else "")
        entry = self.memory_store.add(title, text)
        self._refresh_memory()
        self.rebuild(keep_history=True)
        console.print(f"[green]기억함:[/green] {entry.slug}")

    def _cmd_memory(self) -> None:
        entries = self.memory_store.all_entries()
        if not entries:
            console.print("[dim]저장된 메모리 없음[/dim]")
            return
        for e in entries:
            console.print(f"[bold]{e.slug}[/bold] — {escape(e.title)}")

    def _cmd_compact(self) -> None:
        did = run_sync(self.agent.compact_now(make_event_printer()))
        if not did:
            console.print("[dim]압축할 만큼 대화가 길지 않습니다.[/dim]")

    def _cmd_ps(self) -> None:
        procs = self.procman.list()
        if not procs:
            console.print("[dim]실행 중인 백그라운드 프로세스 없음[/dim]")
            return
        for p in procs:
            console.print(f"[bold]{p.id}[/bold] pid={p.pid} · {escape(p.cmd)}")

    def _cmd_undo(self) -> None:
        result = self.checkpoints.undo()
        if result is None:
            console.print("[yellow]되돌릴 편집이 없습니다.[/yellow]")
            return
        label, restored = result
        console.print(f"[green]되돌림:[/green] {label}")
        for r in restored:
            console.print(f"  {escape(r)}")

    def _cmd_steps(self, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            console.print("사용법: /steps <N>")
            return
        self.max_steps = max(1, int(args[0]))
        self.agent.max_steps = self.max_steps
        console.print(f"최대 스텝: {self.max_steps}")


async def _run_turn(session: ChatSession, text: str) -> None:
    text, refs = expand_file_refs(text, session.root)
    if refs:
        console.print(f"[dim]첨부: {', '.join(refs)}[/dim]")
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
    web: bool = typer.Option(False, "--web", help="웹 도구 활성화."),
    mode: str = typer.Option("", "--mode", help="suggest | auto-edit | full-auto (기본: 설정값)."),
    max_steps: int = typer.Option(20, "--max-steps"),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
    no_context: bool = typer.Option(
        False, "--no-context", help="AGENTS.md 등 프로젝트 컨텍스트 파일을 읽지 않는다."
    ),
    no_map: bool = typer.Option(False, "--no-map", help="저장소 심볼 맵을 넣지 않는다."),
) -> None:
    """대화형으로 에이전트와 작업한다."""
    root_path = root.resolve()
    try:
        approval_mode = ApprovalMode.parse(
            mode or load_permissions(root_path).mode or "suggest"
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

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
        web=web,
        max_steps=max_steps,
        temperature=temperature,
        use_context=not no_context,
        use_map=not no_map,
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
            leftover = session.procman.list()
            if leftover:
                console.print(f"[yellow]백그라운드 프로세스 {len(leftover)}개 정리 중…[/yellow]")
                session.procman.stop_all()

    run_sync(_loop())
    console.print("[dim]종료합니다.[/dim]")

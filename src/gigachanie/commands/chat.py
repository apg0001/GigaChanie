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

from gigachanie.commands._agentui import ask_user, make_approver, make_event_printer
from gigachanie.commands._slashfiles import load_custom_commands
from gigachanie.config import load_config
from gigachanie.context import (
    MemoryStore,
    build_repo_map,
    expand_refs,
    load_project_context,
    load_prompts,
)
from gigachanie.loop.agent import Agent, AgentEvent
from gigachanie.loop.approval import ApprovalMode, build_policy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.checkpoint import CheckpointStore
from gigachanie.loop.hooks import HookRunner
from gigachanie.loop.procman import ProcessManager
from gigachanie.loop.prompt import think_directive
from gigachanie.loop.runlog import RunLogger, git_changed_files
from gigachanie.loop.tools import ToolContext
from gigachanie.permissions import load_permissions
from gigachanie.serving.base import Backend, BackendError, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.session import SessionData, SessionStore

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
  /commands          .agent/commands/*.md 커스텀 명령 목록
  /cost              이 세션 누적 토큰 사용량
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
        prompts: list[str] | None = None,
        think: bool = False,
        think_hard: bool = False,
        resume: SessionData | None = None,
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
        extra, missing = load_prompts(root, prompts or [])
        for name in missing:
            console.print(f"[yellow]![/yellow] 프롬프트를 찾지 못했습니다: {name}")
        directive = think_directive(think, think_hard)
        self.extra_system = "\n\n".join(x for x in (extra, directive) if x) or None
        self.memory_store = MemoryStore(root)
        self._refresh_memory()
        self.compact_at = int((load_config().context or 32000) * 0.7)
        self.checkpoints = CheckpointStore(root)
        self.procman = ProcessManager(root)
        self.perms = load_permissions(root)
        self.usage_prompt = 0
        self.usage_completion = 0
        self.hooks = HookRunner.load(root)
        self.custom_commands = load_custom_commands(root)
        self.sessions = SessionStore(root)
        self.session = resume or SessionData(
            id=SessionStore.new_id(), model_id=getattr(backend, "model", "")
        )
        self.agent = self._new_agent()
        if resume is not None and len(resume.messages) > 1:
            # 시스템 프롬프트(새로 생성) + 이전 대화 이어붙이기
            self.agent.messages = [self.agent.messages[0], *resume.messages[1:]]

    def _persist(self) -> None:
        self.session.messages = list(self.agent.messages)
        if not self.session.title:
            first = next(
                (m.content for m in self.agent.messages if m.role == "user"), ""
            )
            self.session.title = first[:60]
        self.session.model_id = getattr(self.backend, "model", self.session.model_id)
        self.sessions.save(self.session)

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
            ask_user=ask_user,
            hooks=self.hooks if self.hooks.enabled else None,
        )
        return Agent(
            self.backend,
            tools,
            ctx,
            project_context=self.project_context,
            repo_map=self.repo_map,
            memory_index=self.memory_index,
            extra_system=self.extra_system,
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
            self.session = SessionData(
                id=SessionStore.new_id(),
                model_id=getattr(self.backend, "model", ""),
            )
            console.print("[dim]대화 맥락을 초기화했습니다 (새 세션).[/dim]")
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
        elif cmd == "/commands":
            self._cmd_commands()
        elif cmd == "/cost":
            total = self.usage_prompt + self.usage_completion
            console.print(
                f"이 세션 누적 토큰: 입력 {self.usage_prompt} / 출력 "
                f"{self.usage_completion} / 합계 {total}"
            )
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
            f"세션 [cyan]{self.session.id}[/cyan] · 루트 {self.root}"
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

    def _cmd_commands(self) -> None:
        if not self.custom_commands:
            console.print(
                "[dim]커스텀 명령이 없습니다. .agent/commands/<이름>.md 를 만드세요.[/dim]"
            )
            return
        for c in self.custom_commands.values():
            console.print(f"[bold]/{c.name}[/bold]  {escape(c.description)}")

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
    exp = expand_refs(text, session.root)
    attached = exp.text_files + [f"{f}(이미지)" for f in exp.image_files]
    if attached:
        console.print(f"[dim]첨부: {', '.join(attached)}[/dim]")
    for note in exp.notes:
        console.print(f"[yellow]![/yellow] {note}")
    printer = make_event_printer()
    runlog = RunLogger(session.root, task=text, model=session.agent.backend.model)

    def _handler(ev: AgentEvent) -> None:
        runlog.observe(ev)
        printer(ev)

    try:
        result = await session.agent.run(exp.text, on_event=_handler, images=exp.images)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]중단됨[/yellow]")
        session._persist()
        return
    runlog.finish(result, changed_files=git_changed_files(session.root))
    session.usage_prompt += result.usage.prompt_tokens
    session.usage_completion += result.usage.completion_tokens
    session._persist()
    console.print()
    console.rule("[bold]답변[/bold]")
    console.print(result.final_text or "(빈 응답)", markup=False)
    console.print(
        f"[dim]스텝 {result.steps} · {result.stop_reason} · "
        f"토큰 {result.usage.total_tokens} (누적 "
        f"{session.usage_prompt + session.usage_completion})[/dim]"
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
    cont: bool = typer.Option(False, "--continue", "-c", help="가장 최근 세션을 이어간다."),
    resume_id: str = typer.Option("", "--resume", help="특정 세션 ID 를 이어간다."),
    prompts: list[str] = typer.Option(
        [], "--prompt", "-p", help="`.agent/prompts/<이름>.md` 재사용 지시문을 얹는다 (반복 가능)."
    ),
    think: bool = typer.Option(False, "--think", help="답 전에 단계적으로 추론하도록 유도."),
    think_hard: bool = typer.Option(
        False, "--think-hard", help="여러 접근 비교·반례 탐색까지 더 깊게 추론."
    ),
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
        backend = build_backend(root=root_path)
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    resume_data = None
    if cont or resume_id:
        store = SessionStore(root_path)
        resume_data = store.load(resume_id) if resume_id else store.latest()
        if resume_data is None:
            console.print("[yellow]이어갈 세션을 찾지 못했습니다. 새 세션으로 시작합니다.[/yellow]")
        else:
            console.print(
                f"[dim]세션 이어감: {resume_data.id} · {resume_data.turns}턴 · "
                f"{resume_data.title}[/dim]"
            )

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
        prompts=prompts,
        think=think,
        think_hard=think_hard,
        resume=resume_data,
    )

    hist_path = user_config_path("gigachanie", appauthor=False, ensure_exists=True) / "chat_history"
    pt: PromptSession[str] = PromptSession(history=FileHistory(str(hist_path)))

    console.print("[bold]GigaChanie chat[/bold] · /help 로 명령 확인, /exit 로 종료")
    if session.custom_commands:
        console.print(
            f"[dim]커스텀 명령: {', '.join('/' + n for n in session.custom_commands)}[/dim]"
        )
    session._print_info()
    if session.hooks.enabled:
        session.hooks.fire("session_start")

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
                    name = line[1:].split()[0] if len(line) > 1 else ""
                    if name in session.custom_commands:
                        args = line[1 + len(name) :].strip()
                        await _run_turn(
                            session, session.custom_commands[name].expand(args)
                        )
                        continue
                    if not session.handle_slash(line):
                        break
                    continue
                await _run_turn(session, line)
        finally:
            if session.hooks.enabled:
                session.hooks.fire("stop")
            await session.backend.close()
            leftover = session.procman.list()
            if leftover:
                console.print(f"[yellow]백그라운드 프로세스 {len(leftover)}개 정리 중…[/yellow]")
                session.procman.stop_all()

    run_sync(_loop())
    console.print("[dim]종료합니다.[/dim]")

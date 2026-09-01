"""`giga agent` - 에이전트 루프를 한 번 실행한다.

읽기 도구는 항상, 쓰기/실행 도구는 --write 로 활성화한다.
승인 모드는 --mode (suggest | auto-edit | full-auto), --yolo 는 full-auto + write 단축.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from gigachanie.commands._agentui import ask_user, make_approver, make_event_printer
from gigachanie.commands._pick import is_tty as _is_tty
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
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend

console = Console()


def agent(
    task: list[str] = typer.Argument(..., help="에이전트에게 시킬 작업."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트 디렉터리."),
    write: bool = typer.Option(
        False, "--write", "-w", help="쓰기/실행 도구(write_file, run_shell) 활성화."
    ),
    web: bool = typer.Option(
        False, "--web", help="웹 도구(web_search, web_fetch) 활성화."
    ),
    mode: str = typer.Option(
        "", "--mode", help="승인 모드: suggest | auto-edit | full-auto (기본: 설정값 또는 suggest)."
    ),
    yolo: bool = typer.Option(
        False, "--yolo", help="full-auto + write. 확인 없이 전부 실행(주의)."
    ),
    max_steps: int = typer.Option(20, "--max-steps", help="최대 반복 스텝."),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
    no_context: bool = typer.Option(
        False, "--no-context", help="AGENTS.md 등 프로젝트 컨텍스트 파일을 읽지 않는다."
    ),
    no_map: bool = typer.Option(
        False, "--no-map", help="저장소 심볼 맵을 컨텍스트에 넣지 않는다."
    ),
    compact_at: int = typer.Option(
        0, "--compact-at", help="이 토큰 수 초과 시 대화 자동 압축 (0=컨텍스트의 70%)."
    ),
    no_checkpoint: bool = typer.Option(
        False, "--no-checkpoint", help="편집 스냅샷을 남기지 않는다 (giga undo 불가)."
    ),
) -> None:
    """도구를 사용해 코드베이스를 조사하거나 수정한다."""
    task_text = " ".join(task)
    perms = load_permissions(root.resolve())
    try:
        approval_mode = ApprovalMode.parse(
            "full-auto" if yolo else (mode or perms.mode or "suggest")
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    writable = write or yolo
    try:
        backend = build_backend(root=root.resolve())
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    tools = build_registry(writable=writable, web=web)
    policy = build_policy(
        approval_mode,
        None if yolo else make_approver(root.resolve()),
        extra_allow_shell=perms.allow_shell,
        extra_deny_shell=perms.deny_shell,
        allow_paths=perms.allow_paths,
        deny_paths=perms.effective_deny_paths(),
    )
    checkpoints = (
        CheckpointStore(root.resolve())
        if writable and not no_checkpoint
        else None
    )
    procman = ProcessManager(root.resolve()) if writable else None
    ctx = ToolContext(
        root=root.resolve(),
        policy=policy,
        checkpoints=checkpoints,
        procman=procman,
        ask_user=ask_user if _is_tty() else None,
    )
    if not ctx.root.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    pc = None if no_context else load_project_context(ctx.root, Path.cwd())
    rm = None if no_map else build_repo_map(ctx.root, cwd=Path.cwd())
    mem_index = "" if no_context else MemoryStore(ctx.root).index_text()
    task_text, refs = expand_file_refs(task_text, ctx.root)

    ctx_note = ""
    if pc and pc.found:
        ctx_note = f" · 컨텍스트 {', '.join(p.name for p in pc.sources)}"
    if mem_index:
        ctx_note += " · 메모리"
    if rm and rm.found:
        ctx_note += f" · 맵 {len(rm.entries)}파일"
    if refs:
        ctx_note += f" · 첨부 {', '.join(refs)}"
    console.print(
        f"[dim]모델 {backend.model} · 도구 {', '.join(tools.names())} · "
        f"모드 {approval_mode.value}{' · yolo' if yolo else ''} · 루트 {ctx.root}{ctx_note}[/dim]"
    )
    resolved_compact = compact_at or int((load_config().context or 32000) * 0.7)
    handler = make_event_printer()
    ag = Agent(
        backend,
        tools,
        ctx,
        project_context=pc.text if pc else None,
        repo_map=rm.text if rm else None,
        memory_index=mem_index or None,
        max_steps=max_steps,
        temperature=temperature,
        compact_at=resolved_compact,
    )

    async def _go() -> int:
        try:
            result = await ag.run(task_text, on_event=handler)
        finally:
            await backend.close()
            if procman is not None:
                left = procman.list()
                if left:
                    console.print(
                        f"[yellow]백그라운드 프로세스 {len(left)}개 정리 중…[/yellow]"
                    )
                    procman.stop_all()
        console.print()
        console.rule("[bold]결과[/bold]")
        console.print(result.final_text or "(빈 응답)", markup=False)
        console.print(
            f"[dim]스텝 {result.steps} · 종료 {result.stop_reason} · "
            f"토큰 {result.usage.total_tokens}[/dim]"
        )
        return 0 if result.ok else 1

    raise typer.Exit(code=run_sync(_go()))

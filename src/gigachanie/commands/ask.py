"""`giga ask` / `giga ping` - 백엔드 단발성 호출 및 연결 확인.

에이전트 루프(이슈 #5) 전에 백엔드가 제대로 붙는지 확인하는 용도.
"""

from __future__ import annotations

import sys

import typer

from gigachanie.config import load_config
from gigachanie.serving import Message, build_backend
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.ui import make_console

console = make_console()


def ping() -> None:
    """선택된 백엔드/모델에 연결이 되는지 확인한다."""
    try:
        backend = build_backend()
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    cfg = load_config()
    console.print(
        f"백엔드 [cyan]{backend.name}[/cyan] · 모델 [cyan]{backend.model}[/cyan] "
        f"· 툴모드 [cyan]{backend.tool_mode}[/cyan]"
        + (f" · ctx {cfg.context}" if cfg.context else "")
    )

    async def _check() -> tuple[bool, str]:
        try:
            return await backend.health()
        finally:
            await backend.close()

    ok, msg = run_sync(_check())
    if ok:
        console.print(f"[green]✓[/green] {msg}")
    else:
        console.print(f"[red]✗ {msg}[/red]")
        raise typer.Exit(code=1)


def ask(
    prompt: list[str] = typer.Argument(None, help="질문. 생략하면 표준입력에서 읽는다."),
    system: str = typer.Option("", "--system", "-s", help="시스템 프롬프트."),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
    max_tokens: int = typer.Option(0, "--max-tokens", "-m", help="0이면 제한 없음."),
    no_stream: bool = typer.Option(False, "--no-stream", help="스트리밍 비활성화."),
) -> None:
    """모델에 한 번 질문하고 답을 출력한다 (도구 없음)."""
    text = " ".join(prompt) if prompt else sys.stdin.read().strip()
    if not text:
        console.print("[red]질문이 비어 있습니다.[/red]")
        raise typer.Exit(code=1)

    try:
        backend = build_backend()
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    messages: list[Message] = []
    if system:
        messages.append(Message.system(system))
    messages.append(Message.user(text))

    def _emit(delta: str) -> None:
        console.print(delta, end="", markup=False, soft_wrap=True)

    async def _go() -> None:
        try:
            resp = await backend.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens or None,
                stream_cb=None if no_stream else _emit,
            )
            if no_stream:
                console.print(resp.message.content, markup=False, soft_wrap=True)
            else:
                console.print()
            if resp.usage.total_tokens:
                console.print(
                    f"[dim]토큰: 입력 {resp.usage.prompt_tokens} / "
                    f"출력 {resp.usage.completion_tokens}[/dim]"
                )
        finally:
            await backend.close()

    try:
        run_sync(_go())
    except BackendError as exc:
        console.print(f"\n[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

"""`giga setup` - 첫 실행 안내: Ollama 설치 → 모델 선택 → 다운로드."""

from __future__ import annotations

import typer

from gigachanie.commands._pick import is_tty
from gigachanie.serving import ollama_setup
from gigachanie.ui import make_console

console = make_console()


def setup(
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 없이 진행한다."),
    skip_model: bool = typer.Option(False, "--skip-model", help="모델 선택 단계를 건너뛴다."),
) -> None:
    """로컬 실행 환경을 준비한다 (Ollama 설치 + 모델 설정)."""
    console.print("[bold]GigaChanie 설정[/bold]\n")

    # 1) Ollama
    if ollama_setup.is_installed() and ollama_setup.daemon_up():
        console.print("[green]✓[/green] Ollama 설치·실행 확인")
    else:
        interactive = is_tty()
        if not ollama_setup.is_installed():
            proceed = yes or (
                interactive
                and typer.confirm("Ollama 가 없습니다. 지금 설치할까요?", default=True)
            )
            if not proceed:
                console.print("[yellow]Ollama 설치를 건너뜁니다.[/yellow]")
                raise typer.Exit(code=1)
        console.print("[cyan]Ollama 설치/확인 중…[/cyan]")
        ready, msg = ollama_setup.ensure_ready(auto=yes, ask=interactive)
        style = "green" if ready else "yellow"
        console.print(f"[{style}]{msg}[/{style}]")
        if not ready:
            console.print("[dim]설치 후 새 터미널에서 `giga setup` 을 다시 실행하세요.[/dim]")
            raise typer.Exit(code=1 if not ollama_setup.is_installed() else 0)

    if skip_model:
        return

    # 2) 모델
    from gigachanie.commands.model import _pick_model, select_and_save
    from gigachanie.config import load_config
    from gigachanie.providers.registry import default_registry

    cfg = load_config()
    if cfg.model_id:
        console.print(f"[green]✓[/green] 모델 설정됨: {cfg.model_id}")
        console.print("[dim]바꾸려면 `giga model use` (인자 없이 실행).[/dim]")
        return

    console.print()
    chosen = _pick_model(default_registry())
    if not chosen:
        console.print("[dim]모델 선택을 건너뜁니다. 나중에 `giga model use`.[/dim]")
        return
    raise typer.Exit(code=select_and_save(chosen))

"""`giga model ...` - 모델 목록 조회 / 선택 / 다운로드."""

from __future__ import annotations

import subprocess
import sys

import typer
from rich.table import Table

from gigachanie.config import Config, load_config, save_user_config, user_config_file
from gigachanie.providers.hardware import detect_hardware
from gigachanie.providers.recommend import Fit, recommend_models
from gigachanie.providers.registry import Registry, default_registry
from gigachanie.ui import make_console

console = make_console()
app = typer.Typer(name="model", help="모델 목록 조회 / 선택 / 다운로드.", no_args_is_help=True)


@app.command("list")
def list_models(
    family: str = typer.Option("", "--family", "-f", help="계열로 필터 (qwen, llama, ...)."),
    kind: str = typer.Option("", "--kind", "-k", help="종류로 필터 (coder, general, reasoning)."),
    fit_only: bool = typer.Option(
        False, "--fit", help="이 장비에서 실행 가능한 모델만 표시."
    ),
) -> None:
    """레지스트리의 모델 후보를 표로 보여준다."""
    reg = default_registry()
    cfg = load_config()

    fit_map: dict[str, Fit] = {}
    hw = detect_hardware()
    for r in recommend_models(hw, include_unfittable=True):
        fit_map[r.model.id] = r.fit

    table = Table(title="모델 레지스트리", expand=True, show_lines=False)
    table.add_column("ID", style="bold", overflow="fold")
    table.add_column("이름")
    table.add_column("계열")
    table.add_column("종류")
    table.add_column("파라미터", justify="right")
    table.add_column("툴콜")
    table.add_column("컨텍스트", justify="right")
    table.add_column("적합도")
    table.add_column("라이선스")

    for m in reg.models:
        if family and m.family != family:
            continue
        if kind and m.kind != kind:
            continue
        fit = fit_map.get(m.id, Fit.NO)
        if fit_only and fit == Fit.NO:
            continue
        params = (
            f"{m.params_b:.0f}B"
            if m.active_params_b >= m.params_b
            else f"{m.params_b:.0f}B-A{m.active_params_b:.1f}B"
        )
        mark = " [cyan]◀[/cyan]" if m.id == cfg.model_id else ""
        table.add_row(
            m.id + mark,
            m.display,
            m.family,
            m.kind,
            params,
            m.tool_calling,
            f"{m.context // 1024}k",
            fit.label,
            m.license,
        )

    console.print(table)
    console.print(
        "\n[dim]선택: [cyan]giga model use <ID>[/cyan]   "
        "진단·추천: [cyan]giga doctor[/cyan][/dim]"
    )


@app.command("show")
def show() -> None:
    """현재 선택된 모델 설정을 보여준다."""
    cfg = load_config()
    if not cfg.model_id:
        console.print("선택된 모델이 없습니다. [cyan]giga model use <ID>[/cyan] 로 설정하세요.")
        raise typer.Exit(code=1)
    reg = default_registry()
    m = reg.get(cfg.model_id)
    console.print(f"[bold]모델[/bold]     {cfg.model_id}" + (f"  ({m.display})" if m else ""))
    console.print(f"[bold]백엔드[/bold]   {cfg.backend}")
    if cfg.base_url:
        console.print(f"[bold]base_url[/bold] {cfg.base_url}")
    if cfg.quant:
        console.print(f"[bold]양자화[/bold]   {cfg.quant}")
    if cfg.context:
        console.print(f"[bold]컨텍스트[/bold] {cfg.context}")
    console.print(f"[dim]설정 파일: {user_config_file()}[/dim]")


@app.command("use")
def use(
    model_id: str = typer.Argument("", help="레지스트리의 모델 ID (생략하면 대화형 선택)."),
    backend: str = typer.Option("", "--backend", "-b", help="ollama | openai_compat."),
    base_url: str = typer.Option("", "--base-url", help="openai_compat 백엔드 주소."),
    quant: str = typer.Option("", "--quant", "-q", help="양자화 이름 (예: q4_K_M)."),
    context: int = typer.Option(0, "--context", "-c", help="컨텍스트 길이(토큰)."),
    pull: bool = typer.Option(
        False, "--pull", "-p", help="다운로드 실패 시 오류로 종료한다 (강제)."
    ),
    no_pull: bool = typer.Option(
        False, "--no-pull", help="가중치를 받지 않고 설정만 저장한다."
    ),
) -> None:
    """사용할 모델을 선택해 사용자 설정에 저장한다.

    ollama 백엔드이고 모델이 아직 없으면 가중치를 자동으로 다운로드한다.
    대화형 터미널에서는 먼저 확인하고, 비대화 환경에서는 바로 받는다.
    받지 않으려면 --no-pull.
    """
    reg = default_registry()

    if not model_id:
        model_id = _pick_model(reg) or ""
        if not model_id:
            console.print("[dim]선택이 취소되었습니다.[/dim]")
            raise typer.Exit(code=1)

    raise typer.Exit(
        code=select_and_save(
            model_id,
            backend=backend,
            base_url=base_url,
            quant=quant,
            context=context,
            pull=pull,
            no_pull=no_pull,
        )
    )


def select_and_save(
    model_id: str,
    *,
    backend: str = "",
    base_url: str = "",
    quant: str = "",
    context: int = 0,
    pull: bool = False,
    no_pull: bool = False,
) -> int:
    """모델 선택을 사용자 설정에 저장하고 (필요 시) 가중치를 받는다. 종료코드 반환."""
    reg = default_registry()
    m = reg.get(model_id)
    if m is None:
        near = [x.id for x in reg.models if model_id.lower() in x.id.lower()]
        hint = f" 비슷한 항목: {', '.join(near)}" if near else ""
        console.print(f"[red]'{model_id}' 를 레지스트리에서 찾을 수 없습니다.[/red]{hint}")
        console.print("[dim]`giga model list` 로 전체 목록을 확인하세요.[/dim]")
        return 1

    chosen_backend = backend or ("ollama" if "ollama" in m.backends else "openai_compat")
    if chosen_backend not in m.backends:
        console.print(
            f"[red]{m.display} 는 '{chosen_backend}' 백엔드를 지원하지 않습니다.[/red] "
            f"지원: {', '.join(m.backends)}"
        )
        return 1

    if quant and m.quant(quant) is None:
        console.print(
            f"[yellow]![/yellow] '{quant}' 는 알려진 양자화가 아닙니다. "
            f"알려진 값: {', '.join(q.name for q in m.quants)}"
        )

    cfg = load_config().merged(
        model_id=model_id,
        backend=chosen_backend,
        base_url=base_url or None,
        quant=quant or None,
        context=context or None,
    )
    # 저장은 사용자 설정에만 (프로젝트/환경 오버라이드는 유지)
    save_target = Config().merged(
        model_id=cfg.model_id,
        backend=cfg.backend,
        base_url=cfg.base_url,
        quant=cfg.quant,
        context=cfg.context,
    )
    path = save_user_config(save_target)

    console.print(f"[green]선택됨:[/green] {m.display}  ([cyan]{chosen_backend}[/cyan])")
    console.print(f"[dim]저장: {path}[/dim]")
    if chosen_backend == "ollama" and m.ollama_tag:
        if not no_pull and not _ensure_ollama_for_pull():
            return 0
        if _ollama_has(m.ollama_tag):
            console.print(f"[green]✓[/green] ollama 에 '{m.ollama_tag}' 이미 있음")
        else:
            if no_pull:
                do_pull = False
            elif pull:
                do_pull = True
            elif sys.stdin.isatty() and sys.stdout.isatty():
                do_pull = typer.confirm(
                    f"가중치 '{m.ollama_tag}' 가 없습니다. 지금 다운로드할까요?",
                    default=True,
                )
            else:
                do_pull = True  # 비대화 환경: 자동 다운로드

            if do_pull:
                code = _ollama_pull(m.ollama_tag)
                if code != 0:
                    if pull:
                        return code
                    console.print(
                        "[yellow]다운로드를 완료하지 못했습니다. "
                        "나중에 [cyan]giga model pull[/cyan] 로 재시도하세요.[/yellow]"
                    )
            else:
                console.print(
                    f"나중에 받기: [cyan]giga model pull[/cyan]  또는  "
                    f"[cyan]ollama pull {m.ollama_tag}[/cyan]"
                )
    elif chosen_backend == "openai_compat" and not cfg.base_url:
        console.print(
            "[yellow]![/yellow] openai_compat 백엔드는 --base-url 이 필요합니다 "
            "(예: http://localhost:8000/v1)."
        )
    return 0


def _pick_model(reg: Registry) -> str | None:
    from gigachanie.commands._pick import pick

    hw = detect_hardware()
    fit = {r.model.id: r.fit for r in recommend_models(hw, include_unfittable=True)}
    order = {"full": 0, "ok": 1, "tight": 2, "no": 3}
    models = sorted(
        reg.models,
        key=lambda m: (order.get(fit.get(m.id, Fit.NO).value, 3), -m.params_b),
    )
    options = [
        (
            f"{m.display}  [{fit.get(m.id, Fit.NO).label}]  {m.family}/{m.kind}",
            m.id,
        )
        for m in models
    ]
    return pick("사용할 모델 선택", options, text="이 장비 적합도 순 정렬 · Enter 선택")


def _ensure_ollama_for_pull() -> bool:
    """ollama 가 없으면 설치할지 물어보고 설치한다. 준비되면 True."""
    from gigachanie.serving import ollama_setup

    if ollama_setup.is_installed():
        return True

    tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not tty:
        console.print(
            "[yellow]![/yellow] Ollama 미설치. 대화형으로 `giga model use` 를 실행하면 "
            "설치를 안내합니다. 또는 [cyan]giga setup[/cyan] / https://ollama.com"
        )
        return False

    if not typer.confirm(
        "Ollama 가 설치돼 있지 않습니다. 지금 설치할까요?", default=True
    ):
        console.print("[dim]나중에: [cyan]giga setup[/cyan] 또는 https://ollama.com[/dim]")
        return False

    console.print("[cyan]Ollama 설치 중…[/cyan]")
    ready, msg = ollama_setup.ensure_ready(auto=False, ask=True)
    style = "green" if ready else "yellow"
    console.print(f"[{style}]{msg}[/{style}]")
    return ready


def _ollama_has(tag: str) -> bool:
    from gigachanie.serving import ollama_setup

    path = ollama_setup.executable_path()
    if path is None:
        return False
    try:
        out = subprocess.run(
            [path, "list"], capture_output=True, text=True, timeout=4, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    base = tag.split(":")[0]
    return any(line.startswith(base) for line in out.stdout.splitlines()[1:])


def _ollama_pull(tag: str) -> int:
    """`ollama pull <tag>` 를 실행하고 종료코드를 돌려준다."""
    from gigachanie.serving import ollama_setup

    path = ollama_setup.executable_path()
    if path is None:
        console.print("[red]ollama 가 설치되어 있지 않습니다.[/red] https://ollama.com")
        return 1
    console.print(f"[cyan]ollama pull {tag}[/cyan] 실행 중...")
    try:
        return subprocess.run([path, "pull", tag], check=False).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]다운로드 실패: {exc}[/red]")
        return 1


@app.command("pull")
def pull(
    model_id: str = typer.Argument("", help="생략하면 현재 선택된 모델."),
) -> None:
    """선택된(또는 지정한) 모델을 ollama 로 내려받는다."""
    reg = default_registry()
    target_id = model_id or load_config().model_id
    if not target_id:
        console.print("[red]선택된 모델이 없습니다.[/red] `giga model use <ID>` 먼저 실행하세요.")
        raise typer.Exit(code=1)
    m = reg.get(target_id)
    if m is None or not m.ollama_tag:
        console.print(
            f"[red]'{target_id}' 에 ollama 태그가 없습니다.[/red] 수동 설치가 필요합니다."
        )
        raise typer.Exit(code=1)
    raise typer.Exit(code=_ollama_pull(m.ollama_tag))

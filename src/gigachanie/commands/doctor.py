"""`giga doctor` - 하드웨어 감지 및 모델 추천."""

from __future__ import annotations

import dataclasses
import json

import typer
from rich.panel import Panel
from rich.table import Table

from gigachanie.config import load_config
from gigachanie.providers.hardware import HardwareProfile, detect_hardware
from gigachanie.providers.recommend import (
    Fit,
    MemoryBudget,
    Recommendation,
    compute_budget,
    recommend_models,
)
from gigachanie.ui import make_console

console = make_console()

_FIT_STYLE = {
    Fit.FULL: "bold green",
    Fit.OK: "green",
    Fit.TIGHT: "yellow",
    Fit.NO: "red",
}


def _hardware_panel(hw: HardwareProfile, budget: MemoryBudget) -> Panel:
    lines = [
        f"[bold]OS[/bold]          {hw.os_name} ({hw.arch})",
        f"[bold]CPU[/bold]         {hw.cpu_brand}",
        f"[bold]코어[/bold]        물리 {hw.cpu_cores_physical} / 논리 {hw.cpu_cores_logical}",
        f"[bold]RAM[/bold]         {hw.ram_total_gb:.1f} GB (여유 {hw.ram_available_gb:.1f} GB)",
    ]
    if hw.gpus:
        for g in hw.gpus:
            vram = f"{g.vram_gb:.1f} GB" if g.vram_gb else "알 수 없음"
            lines.append(f"[bold]GPU[/bold]         {g.name} · VRAM {vram} ({g.vendor})")
    else:
        lines.append("[bold]GPU[/bold]         감지되지 않음")

    backends = "  ".join(
        f"[green]✓ {b.name}[/green]" if b.available else f"[dim]✗ {b.name}[/dim]"
        for b in hw.backends
    )
    lines.append(f"[bold]백엔드[/bold]      {backends}")
    lines.append("")
    lines.append(
        f"[bold]추론 예산[/bold]    ~{budget.usable_gb:.1f} GB  ({budget.source})"
    )
    lines.append(f"[dim]{budget.note}[/dim]")
    return Panel("\n".join(lines), title="하드웨어", border_style="cyan")


def _recommend_table(recs: list[Recommendation], selected_id: str | None) -> Table:
    table = Table(title="추천 모델 (점수 순)", show_lines=False, expand=True)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("모델", style="bold")
    table.add_column("계열")
    table.add_column("양자화")
    table.add_column("컨텍스트", justify="right")
    table.add_column("적합도")
    table.add_column("속도")
    table.add_column("비고", overflow="fold")

    for i, r in enumerate(recs, start=1):
        mark = " [cyan]◀ 현재[/cyan]" if r.model.id == selected_id else ""
        star = "[yellow]★[/yellow] " if i == 1 else ""
        ctx = "-" if r.max_context == 0 else f"~{r.max_context // 1024}k"
        table.add_row(
            str(i),
            f"{star}{r.model.display}{mark}",
            r.model.family,
            r.quant.name,
            ctx,
            f"[{_FIT_STYLE[r.fit]}]{r.fit.label}[/{_FIT_STYLE[r.fit]}]",
            r.speed.label,
            r.model.notes,
        )
    return table


def _to_json(hw: HardwareProfile, budget: MemoryBudget, recs: list[Recommendation]) -> str:
    payload = {
        "hardware": dataclasses.asdict(hw),
        "budget": dataclasses.asdict(budget),
        "recommendations": [
            {
                "model_id": r.model.id,
                "display": r.model.display,
                "family": r.model.family,
                "quant": r.quant.name,
                "max_context": r.max_context,
                "fit": r.fit.value,
                "speed": r.speed.value,
                "est_tokens_per_sec": r.est_tokens_per_sec,
                "score": r.score,
                "reason": r.reason,
                "ollama": r.ollama_hint,
            }
            for r in recs
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def doctor(
    show_all: bool = typer.Option(
        False, "--all", "-a", help="실행 불가한 모델도 이유와 함께 표시한다."
    ),
    as_json: bool = typer.Option(False, "--json", help="결과를 JSON으로 출력한다."),
    top: int = typer.Option(8, "--top", "-n", help="표시할 추천 모델 수."),
    use: bool = typer.Option(
        False, "--use", "-u", help="진단 후 추천 목록에서 모델을 골라 바로 설정한다."
    ),
) -> None:
    """이 장비를 진단하고 실행 가능한 오픈모델을 추천한다."""
    hw = detect_hardware()
    budget = compute_budget(hw)
    recs = recommend_models(hw, include_unfittable=show_all)

    if as_json:
        console.print_json(_to_json(hw, budget, recs))
        return

    console.print(_hardware_panel(hw, budget))

    for w in hw.warnings:
        console.print(f"[yellow]![/yellow] {w}")

    if not recs:
        console.print(
            "\n[red]이 장비에서 실행 가능한 모델을 찾지 못했습니다.[/red] "
            "`giga doctor --all` 로 이유를 확인하세요."
        )
        raise typer.Exit(code=1)

    shown = recs if show_all else recs[:top]
    cfg = load_config()
    console.print()
    console.print(_recommend_table(shown, cfg.model_id))

    best = recs[0]
    console.print()
    console.print(
        Panel(
            f"추천: [bold green]{best.model.display}[/bold green] "
            f"({best.quant.name})\n{best.reason}\n\n"
            + (
                f"설정: [cyan]giga model use {best.model.id}[/cyan]"
                + (f"\n다운로드: [cyan]{best.ollama_hint}[/cyan]" if best.ollama_hint else "")
            ),
            title="다음 단계",
            border_style="green",
        )
    )

    if use:
        from gigachanie.commands._pick import pick
        from gigachanie.commands.model import select_and_save

        options = [
            (
                f"{r.model.display}  [{r.fit.label}]  {r.speed.label}  "
                f"~{r.max_context // 1024}k",
                r.model.id,
            )
            for r in shown
            if r.fit.value != "no"
        ]
        chosen = pick("설정할 모델 선택", options)
        if chosen:
            raise typer.Exit(code=select_and_save(chosen))
        console.print("[dim]선택 안 함.[/dim]")

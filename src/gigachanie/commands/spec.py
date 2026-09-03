"""`giga spec` - 소형 모델 초안 → 대형 모델 검증으로 구현 계획을 쓴다."""

from __future__ import annotations

from pathlib import Path

import typer

from gigachanie.context import expand_refs
from gigachanie.orchestra.multi import resolve_backend
from gigachanie.orchestra.spec import collaborate
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.ui import make_console

console = make_console()


def spec(
    requirement: list[str] = typer.Argument(..., help="스펙으로 만들 요구사항."),
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트 (@참조·슬롯)."),
    drafter: str = typer.Option(
        "", "--drafter", "-d", help="초안 모델 (ID/슬롯, 생략 시 기본 모델)."
    ),
    reviewer: str = typer.Option(
        "", "--reviewer", "-r", help="검증 모델 (ID/슬롯, 생략 시 기본 모델)."
    ),
    out: Path = typer.Option(None, "--out", "-o", help="최종본을 이 파일에 저장."),
    show_draft: bool = typer.Option(False, "--show-draft", help="초안도 출력."),
) -> None:
    """초안(소형)→검증(대형) 협업으로 구현 계획·설계 문서를 만든다 (도구 미사용)."""
    root = root.resolve()
    req = expand_refs(" ".join(requirement), root).text

    try:
        d_be = resolve_backend(drafter, root)[1] if drafter else build_backend(root=root)
        r_be = (
            resolve_backend(reviewer, root)[1] if reviewer else build_backend(root=root)
        )
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    result = run_sync(collaborate(req, d_be, r_be))

    if show_draft:
        console.rule("[dim]초안[/dim]")
        console.print(result.draft, markup=False)
        console.print()
    console.rule("[bold]최종[/bold]")
    console.print(result.final, markup=False)

    if out is not None:
        out.write_text(result.final + "\n", encoding="utf-8")
        console.print(f"\n[green]저장:[/green] {out}")

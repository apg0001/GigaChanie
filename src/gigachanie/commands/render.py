"""`giga render` - 마크다운을 pptx / docx / html 로 변환한다."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from gigachanie.render import RenderError
from gigachanie.render import render as do_render
from gigachanie.ui import make_console

console = make_console()


def render(
    source: Path = typer.Argument(
        None, help="입력 마크다운 파일 (생략 시 표준입력)."
    ),
    out: Path = typer.Option(..., "--out", "-o", help="출력 파일 (.pptx/.docx/.html)."),
) -> None:
    """마크다운 → 슬라이드/문서. `#`=제목, `##`=슬라이드/섹션, `-`=불릿."""
    if source is not None:
        if not source.is_file():
            console.print(f"[red]파일이 없습니다: {source}[/red]")
            raise typer.Exit(code=1)
        md = source.read_text("utf-8", errors="replace")
    else:
        md = sys.stdin.read()
    if not md.strip():
        console.print("[red]입력이 비어 있습니다.[/red]")
        raise typer.Exit(code=1)

    try:
        result = do_render(md, out.resolve())
    except RenderError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]생성됨:[/green] {result}")

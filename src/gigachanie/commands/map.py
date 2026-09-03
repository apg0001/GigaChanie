"""`giga map` - 저장소 심볼 맵을 출력한다."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from gigachanie.context.repo_map import build_repo_map
from gigachanie.ui import make_console

console = make_console()


def repo_map_cmd(
    root: Path = typer.Option(Path("."), "--root", "-C", help="저장소 루트."),
    budget: int = typer.Option(8000, "--budget", help="맵 텍스트 문자 예산."),
    files: int = typer.Option(400, "--files", help="스캔할 최대 파일 수."),
    as_json: bool = typer.Option(False, "--json", help="JSON 으로 출력."),
) -> None:
    """tree-sitter 없이 심볼을 추출해 참조 랭킹 상위 파일의 개요를 만든다."""
    root = root.resolve()
    if not root.is_dir():
        console.print(f"[red]디렉터리가 아닙니다: {root}[/red]")
        raise typer.Exit(code=1)

    rm = build_repo_map(root, budget_chars=budget, max_files=files)
    if not rm.found:
        console.print("[yellow]심볼을 추출할 소스 파일을 찾지 못했습니다.[/yellow]")
        raise typer.Exit(code=1)

    if as_json:
        payload = [
            {
                "path": e.path,
                "score": round(e.score, 6),
                "n_defs": e.n_defs,
                "symbols": [
                    {"name": s.name, "kind": s.kind, "line": s.line, "parent": s.parent}
                    for s in e.fs.symbols
                ],
            }
            for e in rm.entries
        ]
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    console.print(rm.text)
    total_syms = sum(len(e.fs.symbols) for e in rm.entries)
    console.print(f"\n[dim]{len(rm.entries)} 파일 · 심볼 {total_syms}개 추출[/dim]")

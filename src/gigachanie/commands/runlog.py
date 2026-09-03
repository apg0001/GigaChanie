"""`giga runlog` - 에이전트 실행 로그(`.agent/logs/runs.jsonl`) 조회."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from gigachanie.ui import make_console

console = make_console()

_FILE = Path(".agent") / "logs" / "runs.jsonl"


def _load(root: Path) -> list[dict[str, Any]]:
    path = root / _FILE
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def runlog(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    limit: int = typer.Option(20, "--limit", "-n", help="최근 N개만 표시."),
    stats: bool = typer.Option(False, "--stats", "-s", help="합계·통과율 요약만 출력."),
) -> None:
    """`giga agent` / `giga chat` 실행 기록을 표로 본다."""
    rows = _load(root.resolve())
    if not rows:
        console.print("[dim]실행 로그가 없습니다 (.agent/logs/runs.jsonl).[/dim]")
        return

    if stats:
        ok_count = sum(1 for r in rows if r.get("ok"))
        tok = sum(int(r.get("tokens", {}).get("total", 0)) for r in rows)
        secs = sum(float(r.get("seconds", 0)) for r in rows)
        fails = sum(int(r.get("edit_failures", 0)) for r in rows)
        console.print(
            f"실행 {len(rows)}건 · 성공 {ok_count} "
            f"({ok_count * 100 // len(rows)}%) · "
            f"토큰 {tok:,} · {secs:.0f}s · 편집실패 {fails}"
        )
        return

    table = Table(title=f"실행 로그 (최근 {min(limit, len(rows))}건)", expand=True)
    table.add_column("시각", style="dim", no_wrap=True)
    table.add_column("모델", no_wrap=True)
    table.add_column("결과", no_wrap=True)
    table.add_column("스텝", justify="right")
    table.add_column("토큰", justify="right")
    table.add_column("초", justify="right")
    table.add_column("작업", overflow="fold")
    for r in rows[-limit:]:
        ok = r.get("ok")
        table.add_row(
            str(r.get("ts", "")).replace("T", " "),
            str(r.get("model", "")),
            "[green]OK[/green]" if ok else f"[red]{r.get('stop_reason', 'x')}[/red]",
            str(r.get("steps", "")),
            f"{r.get('tokens', {}).get('total', 0):,}",
            f"{r.get('seconds', 0):.0f}",
            str(r.get("task", "")),
        )
    console.print(table)
    console.print("[dim]요약: giga runlog --stats[/dim]")

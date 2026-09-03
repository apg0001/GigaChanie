"""`giga review` - 변경(diff)을 검토 모델에게 리뷰받는다."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from gigachanie.config import Config, load_config
from gigachanie.orchestra.pipeline import load_pipeline_config, review_diff
from gigachanie.serving.base import BackendError, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.ui import make_console

console = make_console()


def _git_diff(root: Path, staged: bool, rng: str) -> str:
    args = ["git", "-C", str(root), "diff"]
    if staged:
        args.append("--cached")
    if rng:
        args.append(rng)
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout


def review(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
    staged: bool = typer.Option(False, "--staged", help="스테이지된 변경만 리뷰."),
    rng: str = typer.Option("", "--range", "-r", help="git 범위 (예: main..HEAD)."),
    task: str = typer.Option("", "--task", "-t", help="변경의 목적(리뷰 맥락)."),
) -> None:
    """git diff 를 검토 모델(orchestra.yaml 의 pipeline.review, 없으면 현재 모델)에게 리뷰받는다."""
    root = root.resolve()
    diff = _git_diff(root, staged, rng) if sys.stdin.isatty() else sys.stdin.read()

    if not diff.strip():
        console.print("[dim]리뷰할 변경이 없습니다.[/dim]")
        raise typer.Exit(code=0)

    pl = load_pipeline_config(root)
    if pl.review_ref is not None:
        cfg = Config(
            model_id=pl.review_ref.model,
            backend=pl.review_ref.backend,
            base_url=pl.review_ref.base_url,
            context=pl.review_ref.context,
        )
    else:
        cfg = load_config()

    try:
        backend = build_backend(cfg, root=root)
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    async def _go() -> int:
        try:
            result = await review_diff(backend, diff, task=task)
        finally:
            await backend.close()
        console.rule(f"[bold]리뷰[/bold] [dim]({result.model})[/dim]")
        console.print(result.text, markup=False)
        return 1 if result.has_issues else 0

    raise typer.Exit(code=run_sync(_go()))

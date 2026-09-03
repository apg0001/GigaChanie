"""`giga commit` / `giga pr` - git 커밋 메시지·PR 초안을 모델로 생성한다.

프로젝트의 git 규칙(AGENTS.md / CONTRIBUTING.md 에서 추출)을 반영한다.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer
from rich.panel import Panel

from gigachanie.serving.base import BackendError, Message, run_sync
from gigachanie.serving.factory import build_backend
from gigachanie.ui import make_console

console = make_console()

_MAX_DIFF = 14_000

_COMMIT_SYSTEM = """\
당신은 이 저장소의 커밋 메시지를 작성합니다. 아래 git 규칙과 최근 커밋 스타일을 따르세요.
- 제목 한 줄, 그 아래 빈 줄, 본문
- 규칙이 없으면: 제목은 명령형 한국어 요약, 본문은 무엇을·왜를 불릿으로
메시지 본문만 출력하고 코드블록·설명은 붙이지 않습니다.\
"""

_PR_SYSTEM = """\
아래 커밋들로 만들 Pull Request 의 제목과 본문을 작성합니다.
- 첫 줄: 제목(70자 이내)
- 그 다음 빈 줄, 본문: ## 요약 (불릿) / ## 변경점 / ## 테스트
한국어로, 제목/본문만 출력합니다.\
"""


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _git(root: Path, *args: str) -> str:
    try:
        return _run(["git", *args], root).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_rules(root: Path) -> str:
    for name in ("AGENTS.md", "CONTRIBUTING.md", "CLAUDE.md"):
        p = root / name
        if not p.is_file():
            continue
        lines = p.read_text("utf-8", errors="replace").splitlines()
        for i, ln in enumerate(lines):
            if "git" in ln.lower() and ln.lstrip().startswith("#"):
                return "\n".join(lines[i : i + 40])
    return ""


def commit(
    root: Path = typer.Option(Path("."), "--root", "-C", help="저장소 루트."),
    add_all: bool = typer.Option(False, "--all", "-a", help="추적 파일 변경을 모두 스테이지."),
    message: str = typer.Option("", "--message", "-m", help="직접 메시지 지정 (모델 미사용)."),
    push: bool = typer.Option(False, "--push", help="커밋 후 현재 브랜치를 푸시."),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 없이 커밋."),
) -> None:
    """스테이지된 변경으로 커밋한다. 메시지가 없으면 모델이 규칙에 맞게 생성한다."""
    root = root.resolve()
    if not (root / ".git").exists():
        console.print("[red]git 저장소가 아닙니다.[/red]")
        raise typer.Exit(code=1)

    if add_all:
        _git(root, "add", "-A")

    staged = _git(root, "diff", "--cached", "--stat")
    if not staged.strip():
        console.print(
            "[yellow]스테이지된 변경이 없습니다.[/yellow] "
            "`-a` 로 전체 스테이지하거나 `git add` 하세요."
        )
        raise typer.Exit(code=1)
    console.print(staged, markup=False)

    if not message:
        diff = _git(root, "diff", "--cached")[:_MAX_DIFF]
        recent = _git(root, "log", "-5", "--pretty=%s")
        rules = _git_rules(root)
        try:
            backend = build_backend(root=root)
        except BackendError as exc:
            console.print(f"[red]{exc}[/red] (직접 -m 으로 메시지를 지정하세요)")
            raise typer.Exit(code=1) from None
        user = (
            (f"git 규칙:\n{rules}\n\n" if rules else "")
            + (f"최근 커밋 제목:\n{recent}\n\n" if recent else "")
            + f"스테이지된 변경:\n```diff\n{diff}\n```"
        )

        async def _gen() -> str:
            try:
                resp = await backend.chat(
                    [Message.system(_COMMIT_SYSTEM), Message.user(user)],
                    tools=None,
                    temperature=0.0,
                )
                return resp.message.content.strip()
            finally:
                await backend.close()

        message = run_sync(_gen())
        if not message:
            console.print("[red]메시지 생성 실패.[/red]")
            raise typer.Exit(code=1)

    console.print(Panel(message, title="커밋 메시지", border_style="green"))
    if not yes and not typer.confirm("이 메시지로 커밋할까요?", default=True):
        raise typer.Exit(code=1)

    res = _run(["git", "commit", "-m", message], root)
    console.print((res.stdout + res.stderr).strip(), markup=False)
    if res.returncode != 0:
        raise typer.Exit(code=res.returncode)

    if push:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        console.print(f"[cyan]git push -u origin {branch}[/cyan]")
        p = _run(["git", "push", "-u", "origin", branch], root)
        console.print((p.stdout + p.stderr).strip(), markup=False)


def pr(
    root: Path = typer.Option(Path("."), "--root", "-C"),
    base: str = typer.Option("main", "--base", "-b", help="대상 브랜치."),
    create: bool = typer.Option(False, "--create", help="gh 로 실제 PR 을 만든다."),
) -> None:
    """base..HEAD 커밋으로 PR 제목/본문 초안을 만든다 (gh 있으면 --create 로 생성)."""
    root = root.resolve()
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    log = _git(root, "log", f"{base}..HEAD", "--pretty=- %s%n%b")
    if not log.strip():
        console.print(f"[yellow]{base}..HEAD 에 커밋이 없습니다.[/yellow]")
        raise typer.Exit(code=1)
    diffstat = _git(root, "diff", f"{base}...HEAD", "--stat")

    try:
        backend = build_backend(root=root)
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    async def _gen() -> str:
        try:
            resp = await backend.chat(
                [
                    Message.system(_PR_SYSTEM),
                    Message.user(f"커밋:\n{log}\n\n변경 통계:\n{diffstat}"),
                ],
                tools=None,
                temperature=0.0,
            )
            return resp.message.content.strip()
        finally:
            await backend.close()

    draft = run_sync(_gen())
    title, _, body = draft.partition("\n")
    body = body.strip()
    console.print(
        Panel(f"[bold]{title}[/bold]\n\n{body}", title="PR 초안", border_style="cyan")
    )

    if create and shutil.which("gh"):
        if typer.confirm("gh 로 PR 을 생성할까요?", default=True):
            g = _run(
                ["gh", "pr", "create", "--base", base, "--title", title, "--body", body],
                root,
            )
            console.print((g.stdout + g.stderr).strip(), markup=False)
        return

    remote = _git(root, "remote", "get-url", "origin").strip()
    if remote:
        slug = remote.removesuffix(".git").split("github.com")[-1].lstrip(":/")
        console.print(
            f"[dim]수동 생성: https://github.com/{slug}/compare/{base}...{branch}?expand=1[/dim]"
        )

"""`giga self ...` - 자기 점검 / 업데이트 / 자가 수정."""

from __future__ import annotations

import subprocess

import typer
from rich.table import Table

from gigachanie import selfmaint
from gigachanie.commands._pick import is_tty
from gigachanie.ui import make_console

console = make_console()
app = typer.Typer(
    name="self",
    help="자기 점검 / 업데이트 / 자가 수정.",
    no_args_is_help=True,
)


@app.command("info")
def info(
    offline: bool = typer.Option(False, "--offline", help="PyPI 최신 버전 확인을 건너뛴다."),
) -> None:
    """설치 방식·버전·최신 버전 여부를 보여준다."""
    inst = selfmaint.detect_install()
    table = Table(show_header=False, box=None)
    table.add_row("버전", inst.version)
    table.add_row("설치 방식", inst.method)
    table.add_row("위치", str(inst.location or "?"))
    if inst.repo_root:
        table.add_row("소스 저장소", f"{inst.repo_root} {'(git)' if inst.has_git else ''}")
    console.print(table)

    if offline:
        return
    status = selfmaint.check_update()
    if status.latest is None:
        console.print("[dim]PyPI 최신 버전을 확인하지 못했습니다 (오프라인?).[/dim]")
    elif status.behind:
        console.print(
            f"[yellow]업데이트 있음:[/yellow] {status.current} → {status.latest} "
            "· `giga self update`"
        )
    else:
        console.print(f"[green]최신입니다[/green] ({status.current})")


@app.command("check")
def check() -> None:
    """알려진 문제(파이썬 버전·깨진 의존성·임포트 오류)를 훑는다."""
    issues = selfmaint.run_diagnostics()
    status = selfmaint.check_update()
    if status.behind:
        issues.insert(0, f"새 버전 있음: {status.current} → {status.latest}")
    if not issues:
        console.print("[green]이상 없음[/green]")
        return
    console.print("[yellow]발견된 항목:[/yellow]")
    for it in issues:
        console.print(f"  · {it}")
    raise typer.Exit(code=1)


@app.command("update")
def update(
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 없이 진행한다."),
    dry_run: bool = typer.Option(False, "--dry-run", help="실행할 명령만 출력한다."),
    check_only: bool = typer.Option(False, "--check", help="업데이트 여부만 확인한다."),
) -> None:
    """설치 방식에 맞는 방법으로 자신을 최신 버전으로 올린다."""
    inst = selfmaint.detect_install()
    status = selfmaint.check_update()

    if check_only:
        if status.latest is None:
            console.print("[dim]최신 버전 확인 실패.[/dim]")
            raise typer.Exit(code=2)
        if status.behind:
            console.print(f"{status.current} → {status.latest}")
            raise typer.Exit(code=1)
        console.print(f"[green]최신입니다[/green] ({status.current})")
        return

    cmd = selfmaint.update_command(inst)
    if not cmd:
        console.print(
            "[yellow]자동 업데이트 불가:[/yellow] editable 설치인데 git 저장소가 아닙니다."
        )
        raise typer.Exit(code=2)

    if dry_run:
        console.print(" ".join(cmd))
        return

    if not status.behind and status.latest is not None and inst.method != "editable":
        console.print(f"[green]이미 최신입니다[/green] ({status.current})")
        return

    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    if not yes and is_tty() and not typer.confirm("업데이트를 진행할까요?", default=True):
        raise typer.Exit(code=1)

    ok, out = selfmaint.run_update(inst)
    if out:
        console.print(out, markup=False)
    if ok:
        console.print(
            "[green]업데이트 완료.[/green] 새 터미널에서 `giga --version` 으로 확인하세요."
        )
    else:
        console.print("[red]업데이트 실패.[/red]")
        raise typer.Exit(code=1)


@app.command("fix")
def fix(
    task: list[str] = typer.Argument(
        None, help="고칠 문제/요청 설명 (생략하면 테스트·린트·타입 검사 후 실패 수정)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="승인 없이 자동 실행(--yolo). 주의."
    ),
    show: bool = typer.Option(False, "--show", help="실행할 명령만 출력한다."),
) -> None:
    """에이전트를 GigaChanie 자기 저장소에 돌려 문제를 조사·수정한다.

    web_search/web_fetch 로 최신 정보를 찾고, 코드·테스트를 읽어 고친 뒤
    `python -m pytest -q` 로 검증한다. 소스 체크아웃에서만 동작한다.
    """
    inst = selfmaint.detect_install()
    if not inst.can_self_fix or inst.repo_root is None:
        console.print(
            "[red]소스 저장소를 찾지 못했습니다.[/red] "
            "`pip install -e .` 로 소스에서 설치한 경우에만 자가 수정이 가능합니다."
        )
        raise typer.Exit(code=2)

    desc = " ".join(task).strip() if task else selfmaint.DEFAULT_FIX_TASK
    argv = selfmaint.self_fix_argv(inst.repo_root, desc, yolo=yes)

    if show:
        console.print(" ".join(argv))
        return

    console.print(f"[dim]대상 저장소: {inst.repo_root}[/dim]")
    console.print(f"[dim]$ {' '.join(argv[:6])} … [작업 설명 생략][/dim]\n")
    try:
        proc = subprocess.run(argv, check=False)
    except OSError as exc:
        console.print(f"[red]에이전트를 실행할 수 없습니다: {exc}[/red]")
        raise typer.Exit(code=1) from None
    raise typer.Exit(code=proc.returncode)

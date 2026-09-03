"""`giga policy` - 이 디렉터리에 적용되는 승인·권한 규칙을 보여준다."""

from __future__ import annotations

from pathlib import Path

import typer

from gigachanie.loop.approval import ApprovalMode, build_policy
from gigachanie.permissions import load_permissions
from gigachanie.ui import make_console

console = make_console()


def policy(
    root: Path = typer.Option(Path("."), "--root", "-C", help="작업 루트."),
) -> None:
    """사용자·프로젝트 permissions.yaml 을 병합한 결과를 출력한다."""
    perms = load_permissions(root.resolve())
    pol = build_policy(
        ApprovalMode.parse(perms.mode or "suggest"),
        None,
        extra_allow_shell=perms.allow_shell,
        extra_deny_shell=perms.deny_shell,
        allow_paths=perms.allow_paths,
        deny_paths=perms.effective_deny_paths(),
    )
    console.print(f"[bold]승인 모드[/bold]  {pol.mode.value}"
                  + ("" if perms.mode else "  [dim](기본값)[/dim]"))
    console.print()
    console.print("[bold]셸 자동 허용[/bold] (정규식)")
    for p in pol.allow_shell:
        console.print(f"  [green]+[/green] {p}")
    console.print("\n[bold]셸 차단[/bold] (정규식)")
    for p in pol.deny_shell:
        console.print(f"  [red]-[/red] {p}")
    console.print("\n[bold]편집 허용 경로[/bold] (glob)")
    if pol.allow_paths:
        for p in pol.allow_paths:
            console.print(f"  [green]+[/green] {p}")
    else:
        console.print("  [dim](없음 - 모든 편집이 모드 규칙을 따름)[/dim]")
    console.print("\n[bold]보호 경로[/bold] (glob, 편집/생성 차단)")
    for p in pol.deny_paths:
        console.print(f"  [red]-[/red] {p}")
    console.print(
        "\n[dim]편집하려면: <root>/.agent/permissions.yaml 또는 "
        "~/.config/gigachanie/permissions.yaml[/dim]"
    )

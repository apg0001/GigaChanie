"""대화형 선택 UI 헬퍼.

TTY 면 prompt_toolkit 라디오 목록(화살표 + Enter), 아니면 번호 입력으로 폴백한다.
비대화(파이프/테스트)면 None 을 돌려준다.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from gigachanie.ui import make_console

console = make_console()


def is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


_is_tty = is_tty


def pick(
    title: str,
    options: Sequence[tuple[str, str]],
    *,
    text: str = "화살표로 이동, Enter 로 선택, Esc 로 취소",
) -> str | None:
    """options: (표시 라벨, 반환 값) 목록. 선택된 값 또는 None."""
    if not options:
        return None
    if not _is_tty():
        return None

    from gigachanie.ui import plain

    if plain():  # 스크린리더: 번호 입력이 더 안전
        return _numbered_fallback(title, options)

    try:
        from prompt_toolkit.shortcuts import radiolist_dialog

        result = radiolist_dialog(
            title=title,
            text=text,
            values=[(value, label) for label, value in options],
        ).run()
        return result
    except Exception:
        return _numbered_fallback(title, options)


def _numbered_fallback(title: str, options: Sequence[tuple[str, str]]) -> str | None:
    console.print(f"[bold]{title}[/bold]")
    for i, (label, _) in enumerate(options, start=1):
        console.print(f"  {i}. {label}")
    try:
        raw = input("번호 (빈 입력=취소): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw.isdigit():
        return None
    idx = int(raw)
    if 1 <= idx <= len(options):
        return options[idx - 1][1]
    return None

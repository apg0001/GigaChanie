"""출력 콘솔 팩토리 (접근성).

`NO_COLOR`(표준) 또는 `GIGA_NO_COLOR` 환경변수가 있으면 색·스타일 없이,
`GIGA_PLAIN` 이면 그에 더해 애니메이션(스피너·프로그레스)도 끈다.
스크린리더 사용자는 `GIGA_PLAIN=1` 을 권장한다.
"""

from __future__ import annotations

import contextlib
import os
import sys

from rich.console import Console


def _fix_windows_console() -> None:
    """Windows 콘솔(cp949)에서 유니코드 기호(✔ ✗ → 등) 출력 시 죽지 않도록.

    stdout/stderr 를 UTF-8 로 재설정한다. 파이프·이미 UTF-8 이면 무해.
    """
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


_fix_windows_console()


def no_color() -> bool:
    return bool(os.environ.get("NO_COLOR") or os.environ.get("GIGA_NO_COLOR"))


def plain() -> bool:
    return bool(os.environ.get("GIGA_PLAIN"))


def make_console(**kwargs: object) -> Console:
    opts: dict[str, object] = {"no_color": no_color()}
    if plain():
        opts["no_color"] = True
        opts["highlight"] = False
        opts["emoji"] = False
    opts.update(kwargs)
    return Console(**opts)  # type: ignore[arg-type]

"""출력 콘솔 팩토리 (접근성).

`NO_COLOR`(표준) 또는 `GIGA_NO_COLOR` 환경변수가 있으면 색·스타일 없이,
`GIGA_PLAIN` 이면 그에 더해 애니메이션(스피너·프로그레스)도 끈다.
스크린리더 사용자는 `GIGA_PLAIN=1` 을 권장한다.
"""

from __future__ import annotations

import os

from rich.console import Console


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

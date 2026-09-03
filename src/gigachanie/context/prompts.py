"""재사용 지시문: `.agent/prompts/*.md` 를 시스템 프롬프트에 얹는다.

커스텀 슬래시 명령(`.agent/commands/`, 한 번 실행하는 작업)과 달리,
프롬프트는 세션 내내 유지되는 지시문이다(코딩 스타일, 말투, 금지 사항 등).
`giga agent -p <이름>` / `giga chat -p <이름>` 로 불러온다(여러 개 가능).

전역(`~/.config/gigachanie/prompts/`) → 프로젝트(`.agent/prompts/`) 순서로
이름이 겹치면 프로젝트 것이 이긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path

_REL = Path(".agent") / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    body: str
    source: Path


def _dirs(root: Path) -> list[Path]:
    return [
        user_config_path("gigachanie", appauthor=False, ensure_exists=False) / "prompts",
        root / _REL,
    ]


def list_prompts(root: Path) -> list[Prompt]:
    out: dict[str, Prompt] = {}
    for d in _dirs(root):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                body = f.read_text("utf-8", errors="replace").strip()
            except OSError:
                continue
            if body:
                out[f.stem] = Prompt(name=f.stem, body=body, source=f)
    return list(out.values())


def load_prompts(root: Path, names: list[str]) -> tuple[str, list[str]]:
    """이름 목록에 해당하는 프롬프트 본문을 합쳐 반환. (합친 텍스트, 못 찾은 이름들)."""
    if not names:
        return "", []
    available = {p.name: p for p in list_prompts(root)}
    parts: list[str] = []
    missing: list[str] = []
    for n in names:
        p = available.get(n)
        if p is None:
            missing.append(n)
        else:
            parts.append(p.body)
    return "\n\n".join(parts), missing

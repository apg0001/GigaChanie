"""컨텍스트 주입 예산.

시스템 프롬프트에 넣는 프로젝트 컨텍스트·repo map·메모리 목차의 총량을
모델 컨텍스트 창의 일정 비율로 제한하고, 세 항목에 나눠 배분한다.
토큰 ≈ 문자수 / 3.5 (한국어·코드 혼합 대략치)로 환산한다.
"""

from __future__ import annotations

from dataclasses import dataclass

_CHARS_PER_TOKEN = 3.5
_INJECT_SHARE = 0.22  # 컨텍스트 창의 이 비율까지만 주입에 사용
_SPLIT = {"project": 0.4, "map": 0.4, "memory": 0.2}
_MIN = {"project": 2000, "map": 3000, "memory": 1000}


@dataclass(frozen=True)
class ContextBudget:
    project_chars: int
    map_chars: int
    memory_chars: int


def allocate(context_tokens: int | None) -> ContextBudget:
    ctx = context_tokens or 32000
    total = max(int(ctx * _CHARS_PER_TOKEN * _INJECT_SHARE), 8000)
    return ContextBudget(
        project_chars=max(int(total * _SPLIT["project"]), _MIN["project"]),
        map_chars=max(int(total * _SPLIT["map"]), _MIN["map"]),
        memory_chars=max(int(total * _SPLIT["memory"]), _MIN["memory"]),
    )


def clip(text: str | None, limit: int) -> str | None:
    if not text or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n… (컨텍스트 예산으로 잘림)"

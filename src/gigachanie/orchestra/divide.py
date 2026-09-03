"""작업 분할: 플래너가 하위 작업으로 쪼갠다.

각 하위 작업은 독립된 `giga agent` 실행(자체 컨텍스트·runlog)으로 순차 처리한다.
같은 저장소를 건드리므로 병렬이 아니라 순차로 돌린다.
"""

from __future__ import annotations

import re

from gigachanie.serving.base import Backend, Message

_PLANNER_SYS = (
    "너는 작업을 잘게 나누는 플래너다. 주어진 목표를, 순서대로 하나씩 수행하면 "
    "목표가 달성되는 3~6개의 하위 작업으로 나눠라. 각 하위 작업은 한 줄로, 무엇을 "
    "어느 파일에 할지 구체적으로. 번호·불릿·설명 없이 줄바꿈으로만 구분해라."
)


async def plan_subtasks(backend: Backend, goal: str, *, max_items: int = 6) -> list[str]:
    resp = await backend.chat(
        [Message.system(_PLANNER_SYS), Message.user(goal)], tools=None
    )
    lines = []
    for raw in resp.message.content.splitlines():
        s = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", raw).strip()
        if s:
            lines.append(s)
    return lines[:max_items]

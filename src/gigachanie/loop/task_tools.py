"""작업 목록 도구.

다단계 작업을 할 때 에이전트가 스스로 체크리스트를 만들고 갱신한다.
목록은 `ctx.scratch["tasks"]` 에 저장되고, CLI 이벤트 프린터와 `giga serve`
가 이를 예쁘게 렌더한다. 파일에는 쓰지 않는다(세션 범위).
"""

from __future__ import annotations

from typing import Any

from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult

_STATUS = {
    "pending": "[ ]",
    "todo": "[ ]",
    "active": "[~]",
    "in_progress": "[~]",
    "doing": "[~]",
    "done": "[x]",
    "completed": "[x]",
}
_CANON = {
    "pending": "pending",
    "todo": "pending",
    "active": "active",
    "in_progress": "active",
    "doing": "active",
    "done": "done",
    "completed": "done",
}


def render_tasks(tasks: list[dict[str, str]]) -> str:
    if not tasks:
        return "(작업 목록 비어 있음)"
    lines = [f"{_STATUS.get(t['status'], '[ ]')} {t['title']}" for t in tasks]
    done = sum(1 for t in tasks if t["status"] == "done")
    return "\n".join(lines) + f"\n— {done}/{len(tasks)} 완료"


async def _update_tasks(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    raw = args.get("tasks")
    if not isinstance(raw, list) or not raw:
        raise ToolError("tasks 는 비어 있지 않은 배열이어야 합니다.")

    tasks: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ToolError("각 항목은 {title, status} 객체여야 합니다.")
        title = str(item.get("title") or item.get("content") or "").strip()
        if not title:
            raise ToolError("각 항목에 title 이 필요합니다.")
        status = _CANON.get(str(item.get("status", "pending")).lower(), "pending")
        tasks.append({"title": title, "status": status})

    if sum(1 for t in tasks if t["status"] == "active") > 1:
        # 여러 개를 동시에 진행 중으로 두지 않도록 첫 개만 남긴다.
        seen = False
        for t in tasks:
            if t["status"] == "active":
                if seen:
                    t["status"] = "pending"
                seen = True

    ctx.scratch["tasks"] = tasks
    return ToolResult(content=render_tasks(tasks))


def register_task_tools(reg: ToolRegistry) -> None:
    reg.register_func(
        "update_tasks",
        "다단계 작업의 체크리스트를 만들거나 갱신한다. 매 호출마다 전체 목록을 "
        "다시 넘긴다(부분 갱신 아님). 3단계 이상 걸리는 작업이면 시작할 때 한 번 "
        "계획을 세우고, 각 단계를 시작/완료할 때 status 를 바꿔 다시 호출한다. "
        "status: pending(대기) | active(진행 중, 하나만) | done(완료).",
        {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "active", "done"],
                            },
                        },
                        "required": ["title", "status"],
                    },
                }
            },
            "required": ["tasks"],
        },
        _update_tasks,
    )

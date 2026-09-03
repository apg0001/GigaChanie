"""작업 목록 도구(update_tasks) 테스트."""

from __future__ import annotations

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.loop.agent import Agent, AgentEvent
from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.task_tools import register_task_tools, render_tasks
from gigachanie.loop.tools import ToolContext, ToolRegistry
from gigachanie.serving.base import run_sync


def _reg() -> ToolRegistry:
    r = ToolRegistry()
    register_task_tools(r)
    return r


def test_update_tasks_저장_및_렌더(tmp_path: Path) -> None:
    ctx = ToolContext(root=tmp_path)
    tool = _reg().get("update_tasks")
    assert tool is not None
    res = run_sync(
        tool.run(
            {
                "tasks": [
                    {"title": "조사", "status": "done"},
                    {"title": "구현", "status": "active"},
                    {"title": "테스트", "status": "pending"},
                ]
            },
            ctx,
        )
    )
    assert not res.is_error
    assert "[x] 조사" in res.content
    assert "[~] 구현" in res.content
    assert "1/3 완료" in res.content
    assert ctx.scratch["tasks"][1] == {"title": "구현", "status": "active"}


def test_active_는_하나만(tmp_path: Path) -> None:
    ctx = ToolContext(root=tmp_path)
    tool = _reg().get("update_tasks")
    run_sync(
        tool.run(
            {
                "tasks": [
                    {"title": "a", "status": "active"},
                    {"title": "b", "status": "active"},
                ]
            },
            ctx,
        )
    )
    statuses = [t["status"] for t in ctx.scratch["tasks"]]
    assert statuses == ["active", "pending"]


def test_별칭_status(tmp_path: Path) -> None:
    ctx = ToolContext(root=tmp_path)
    tool = _reg().get("update_tasks")
    run_sync(
        tool.run({"tasks": [{"title": "x", "status": "in_progress"}]}, ctx)
    )
    assert ctx.scratch["tasks"][0]["status"] == "active"


def test_render_tasks_빈목록() -> None:
    assert "비어" in render_tasks([])


def test_update_tasks_기본_레지스트리에_포함(tmp_path: Path) -> None:
    assert "update_tasks" in default_readonly_registry().names()


def test_에이전트가_체크리스트_갱신(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response(
                "update_tasks",
                {"tasks": [{"title": "1단계", "status": "active"}]},
            ),
            text_response("완료"),
        ]
    )
    agent = Agent(backend, default_readonly_registry(), ToolContext(root=tmp_path))
    events: list[AgentEvent] = []
    run_sync(agent.run("여러 단계 작업", on_event=events.append))
    results = [e for e in events if e.kind == "tool_result" and e.tool_name == "update_tasks"]
    assert results and "[~] 1단계" in results[0].text

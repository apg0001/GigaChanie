"""서브에이전트 도구(run_subagent) 테스트."""

from __future__ import annotations

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.loop.agent import Agent
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.subagent import register_subagent_tool
from gigachanie.loop.tools import ToolContext, ToolRegistry
from gigachanie.serving.base import run_sync


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO))


def test_등록_및_기본_스코프(tmp_path: Path) -> None:
    reg = ToolRegistry()
    ctx = _ctx(tmp_path)
    register_subagent_tool(
        reg, backend=ScriptedBackend([]), root=tmp_path, parent_ctx=ctx,
        parent_writable=False,
    )
    assert "run_subagent" in reg.names()


def test_깊이_제한(tmp_path: Path) -> None:
    reg = ToolRegistry()
    ctx = _ctx(tmp_path)
    register_subagent_tool(
        reg, backend=ScriptedBackend([]), root=tmp_path, parent_ctx=ctx,
        parent_writable=False, depth=2,
    )
    assert "run_subagent" not in reg.names()


def test_서브에이전트_실행_결과_반환(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("secret42", encoding="utf-8")
    # 부모: run_subagent 호출 → 최종 답변
    # 서브: read_file → 최종 답변
    backend = ScriptedBackend(
        [
            tool_response("run_subagent", {"task": "a.txt 내용을 알려줘"}),
            tool_response("read_file", {"path": "a.txt"}),
            text_response("내용은 secret42 입니다."),
            text_response("서브에이전트가 secret42 라고 했습니다."),
        ]
    )
    tools = default_readonly_registry()
    ctx = _ctx(tmp_path)
    register_subagent_tool(
        tools, backend=backend, root=tmp_path, parent_ctx=ctx, parent_writable=False
    )
    agent = Agent(backend, tools, ctx)
    result = run_sync(agent.run("서브에이전트로 a.txt 를 읽어줘"))
    assert result.ok
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert any("secret42" in m.content and "서브에이전트" in m.content for m in tool_msgs)


def test_쓰기는_부모가_허용해야(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response("run_subagent", {"task": "z.txt 만들어", "write": True}),
            text_response("서브 결과: 쓰기 도구가 없어 못 만듦"),
            text_response("부모 종료"),
        ]
    )
    tools = default_readonly_registry()
    ctx = _ctx(tmp_path)  # parent_writable=False
    register_subagent_tool(
        tools, backend=backend, root=tmp_path, parent_ctx=ctx, parent_writable=False
    )
    agent = Agent(backend, tools, ctx)
    run_sync(agent.run("만들어"))
    assert not (tmp_path / "z.txt").exists()

"""ask_user 도구 테스트."""

from pathlib import Path

import pytest
from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.loop.agent import Agent
from gigachanie.loop.builtin_tools import build_registry, default_readonly_registry
from gigachanie.loop.tools import ToolContext, ToolError
from gigachanie.serving.base import run_sync


def _run(args: dict, ctx: ToolContext):
    tool = default_readonly_registry().get("ask_user")
    assert tool is not None
    return run_sync(tool.run(args, ctx))


def test_도구_등록됨() -> None:
    assert default_readonly_registry().get("ask_user") is not None
    assert build_registry(writable=True).get("ask_user") is not None


def test_ask_user_없으면_가정안내(tmp_path: Path) -> None:
    res = _run({"question": "어떤 DB?"}, ToolContext(root=tmp_path))
    assert not res.is_error
    assert "가정" in res.content


def test_ask_user_콜백_호출_및_선택지(tmp_path: Path) -> None:
    calls: list[tuple] = []

    def asker(q: str, opts: list[str], custom: bool) -> str:
        calls.append((q, tuple(opts), custom))
        return opts[1]

    ctx = ToolContext(root=tmp_path, ask_user=asker)
    res = _run(
        {"question": "SQLite 와 Postgres 중?", "options": ["SQLite", "Postgres"]}, ctx
    )
    assert calls[0][0] == "SQLite 와 Postgres 중?"
    assert calls[0][1] == ("SQLite", "Postgres")
    assert "Postgres" in res.content


def test_ask_user_빈답변(tmp_path: Path) -> None:
    ctx = ToolContext(root=tmp_path, ask_user=lambda *_a: "  ")
    res = _run({"question": "x"}, ctx)
    assert "가정" in res.content


def test_question_필수(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        _run({"options": ["a"]}, ToolContext(root=tmp_path))


def test_에이전트_루프에서_질문_후_진행(tmp_path: Path) -> None:
    answers = iter(["옵션 B"])
    ctx = ToolContext(root=tmp_path, ask_user=lambda *_a: next(answers))
    backend = ScriptedBackend(
        [
            tool_response(
                "ask_user",
                {"question": "A 와 B 중 뭘로?", "options": ["옵션 A", "옵션 B"]},
            ),
            text_response("옵션 B 로 진행했습니다."),
        ]
    )
    agent = Agent(backend, default_readonly_registry(), ctx)
    result = run_sync(agent.run("뭔가 해줘"))
    assert result.ok
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert tool_msgs and "옵션 B" in tool_msgs[0].content

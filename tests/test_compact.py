"""세션 대화 압축 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.loop.agent import Agent
from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.compact import compact, estimate_tokens, should_compact
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import Message, run_sync


def _msgs(n: int) -> list[Message]:
    out = [Message.system("시스템 프롬프트")]
    for i in range(n):
        out.append(Message.user(f"질문 {i} " + "가" * 50))
        out.append(Message.assistant(f"답변 {i} " + "나" * 50))
    return out


def test_estimate_와_should_compact() -> None:
    small = _msgs(1)
    assert estimate_tokens(small) > 0
    assert should_compact(small, limit=None) is False
    assert should_compact(small, limit=100000) is False
    assert should_compact(_msgs(50), limit=500) is True


def test_compact_구조(tmp_path: Path) -> None:
    backend = ScriptedBackend([text_response("- 목표: X\n- 확인: Y\n- 다음: Z")])
    msgs = _msgs(10)
    new, did, used = run_sync(compact(backend, msgs, keep_recent=4))
    assert did
    assert used.total_tokens >= 0
    assert new[0].role == "system"
    assert "요약" in new[1].content and "목표: X" in new[1].content
    # 최근 메시지는 그대로 유지
    assert new[-1].content == msgs[-1].content
    assert len(new) < len(msgs)


def test_compact_짧으면_그대로(tmp_path: Path) -> None:
    backend = ScriptedBackend([text_response("요약")])
    msgs = _msgs(1)
    new, did, _used = run_sync(compact(backend, msgs))
    assert not did
    assert new == msgs


def test_compact_빈요약이면_스킵() -> None:
    backend = ScriptedBackend([text_response("   ")])
    new, did, _used = run_sync(compact(backend, _msgs(6)))
    assert not did


def test_compact_now_수동_압축(tmp_path: Path) -> None:
    backend = ScriptedBackend([text_response("- 목표: 리팩터\n- 다음: 테스트")])
    agent = Agent(backend, default_readonly_registry(), ToolContext(root=tmp_path))
    agent.messages = _msgs(10)
    events: list = []
    did = run_sync(agent.compact_now(events.append))
    assert did
    assert len(agent.messages) < 21
    assert any(e.kind == "compact" for e in events)
    assert "목표: 리팩터" in agent.messages[1].content


def test_agent_루프_자동압축_트리거(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"a{i}.txt").write_text("x" * 500, encoding="utf-8")
    backend = ScriptedBackend(
        [tool_response("read_file", {"path": f"a{i}.txt"}, call_id=f"c{i}") for i in range(5)]
        + [text_response("요약: 파일들을 읽음"), text_response("최종 답변")]
    )
    agent = Agent(
        backend,
        default_readonly_registry(),
        ToolContext(root=tmp_path),
        compact_at=150,
        max_steps=12,
    )
    events: list = []
    result = run_sync(agent.run("파일들 읽어줘", on_event=events.append))
    assert result.ok
    assert any(e.kind == "compact" for e in events)


def test_자동압축_토큰이_사용량에_집계된다(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"a{i}.txt").write_text("x" * 500, encoding="utf-8")
    backend = ScriptedBackend(
        [tool_response("read_file", {"path": f"a{i}.txt"}, call_id=f"c{i}") for i in range(5)]
        + [text_response("요약: 파일들을 읽음"), text_response("최종 답변")]
    )
    agent = Agent(
        backend,
        default_readonly_registry(),
        ToolContext(root=tmp_path),
        compact_at=150,
        max_steps=12,
    )
    events: list = []
    result = run_sync(agent.run("파일들 읽어줘", on_event=events.append))
    assert any(e.kind == "compact" for e in events)
    # 대본 응답은 모두 Usage(1,1). 압축 호출 포함 모든 chat 호출이 집계돼야 한다.
    assert result.usage.total_tokens == 2 * len(backend.received)


def test_compact_at_None이면_비활성(tmp_path: Path) -> None:
    backend = ScriptedBackend([text_response("답")])
    agent = Agent(
        backend, default_readonly_registry(), ToolContext(root=tmp_path), compact_at=None
    )
    result = run_sync(agent.run("hi"))
    assert result.ok
    # 압축 요약 호출이 없었으므로 대본 1개만 소비
    assert len(backend.received) == 1

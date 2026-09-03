"""대화 세션 저장/재개 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.commands.chat import ChatSession
from gigachanie.loop.approval import ApprovalMode
from gigachanie.serving.base import Message, run_sync
from gigachanie.session import SessionData, SessionStore

runner = CliRunner()


def _sess(tmp_path: Path, **kw) -> ChatSession:
    return ChatSession(
        kw.pop("backend", ScriptedBackend([])),
        tmp_path,
        mode=ApprovalMode.SUGGEST,
        writable=False,
        max_steps=20,
        temperature=0.0,
        use_context=False,
        use_map=False,
        resume=kw.pop("resume", None),
    )


def test_store_save_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    data = SessionData(id="s1", title="테스트", model_id="m")
    data.messages = [
        Message.system("sys"),
        Message.user("안녕"),
        Message.assistant("반가워요"),
    ]
    store.save(data)
    loaded = store.load("s1")
    assert loaded is not None
    assert loaded.title == "테스트"
    assert [m.role for m in loaded.messages] == ["system", "user", "assistant"]
    assert loaded.turns == 1


def test_store_tool_call_직렬화(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    from gigachanie.serving.base import ToolCall

    data = SessionData(id="s2")
    data.messages = [
        Message.assistant("", [ToolCall(id="c1", name="read_file", arguments={"path": "a"})]),
        Message(role="tool", content="내용", tool_call_id="c1", name="read_file"),
    ]
    store.save(data)
    loaded = store.load("s2")
    assert loaded.messages[0].tool_calls[0].name == "read_file"
    assert loaded.messages[1].tool_call_id == "c1"


def test_store_이미지_첨부_라운드트립(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    data = SessionData(id="img1")
    data.messages = [
        Message.user("이 이미지 봐줘", ["data:image/png;base64,AAAA"]),
        Message.assistant("확인했어요"),
    ]
    store.save(data)
    loaded = store.load("img1")
    assert loaded is not None
    assert loaded.messages[0].images == ["data:image/png;base64,AAAA"]


def test_latest(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.save(SessionData(id="old", title="옛날"))
    import time

    time.sleep(0.02)
    store.save(SessionData(id="new", title="최근"))
    assert store.latest().id == "new"


def test_chat_턴마다_저장(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response("noop", {}),  # 등록 안 된 도구 → 에러 피드백
            text_response("답변1"),
        ]
    )
    s = _sess(tmp_path, backend=backend)
    from gigachanie.commands.chat import _run_turn

    run_sync(_run_turn(s, "첫 질문"))
    loaded = SessionStore(tmp_path).load(s.session.id)
    assert loaded is not None
    assert any(m.content == "첫 질문" for m in loaded.messages)
    assert loaded.title == "첫 질문"


def test_resume_로_대화_이어감(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    prev = SessionData(id="p1", title="이전")
    prev.messages = [
        Message.system("sys"),
        Message.user("이전 질문"),
        Message.assistant("이전 답"),
    ]
    store.save(prev)

    s = _sess(tmp_path, resume=store.load("p1"))
    roles = [m.role for m in s.agent.messages]
    assert roles == ["system", "user", "assistant"]
    assert s.agent.messages[1].content == "이전 질문"
    assert s.session.id == "p1"


def test_giga_sessions_cli(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.save(SessionData(id="abc123", title="작업 A"))
    result = runner.invoke(app, ["sessions", "list", "-C", str(tmp_path)])
    assert result.exit_code == 0 and "abc123" in result.stdout

    rm = runner.invoke(app, ["sessions", "rm", "abc123", "-C", str(tmp_path)])
    assert rm.exit_code == 0
    assert runner.invoke(app, ["sessions", "rm", "abc123", "-C", str(tmp_path)]).exit_code == 1

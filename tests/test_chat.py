"""chat REPL 의 슬래시 명령 / 세션 상태 테스트 (PromptSession 없이 ChatSession 직접)."""

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.commands.chat import ChatSession
from gigachanie.loop.approval import ApprovalMode
from gigachanie.serving.base import Message, run_sync


def _session(tmp_path: Path, **kw) -> ChatSession:
    backend = kw.pop("backend", ScriptedBackend([]))
    return ChatSession(
        backend,
        tmp_path,
        mode=kw.pop("mode", ApprovalMode.SUGGEST),
        writable=kw.pop("writable", False),
        max_steps=kw.pop("max_steps", 20),
        temperature=kw.pop("temperature", 0.0),
    )


def test_exit_명령은_False(tmp_path: Path) -> None:
    s = _session(tmp_path)
    assert s.handle_slash("/exit") is False
    assert s.handle_slash("/quit") is False


def test_help_와_알수없는명령은_계속(tmp_path: Path) -> None:
    s = _session(tmp_path)
    assert s.handle_slash("/help") is True
    assert s.handle_slash("/blah") is True


def test_diff_명령(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("v2\n", encoding="utf-8")

    s = _session(tmp_path)
    assert s.handle_slash("/diff") is True  # 예외 없이 처리


def test_write_토글이_도구목록에_반영(tmp_path: Path) -> None:
    s = _session(tmp_path)
    assert "write_file" not in s.agent.tools.names()
    s.handle_slash("/write on")
    assert s.writable is True
    assert "write_file" in s.agent.tools.names()
    assert "apply_edit" in s.agent.tools.names()
    s.handle_slash("/write off")
    assert "write_file" not in s.agent.tools.names()


def test_mode_변경(tmp_path: Path) -> None:
    s = _session(tmp_path)
    s.handle_slash("/mode auto-edit")
    assert s.mode is ApprovalMode.AUTO_EDIT
    s.handle_slash("/mode 이상한값")
    assert s.mode is ApprovalMode.AUTO_EDIT  # 변경 안 됨


def test_steps_변경(tmp_path: Path) -> None:
    s = _session(tmp_path)
    s.handle_slash("/steps 7")
    assert s.max_steps == 7
    assert s.agent.max_steps == 7


def test_clear_는_맥락_초기화(tmp_path: Path) -> None:
    s = _session(tmp_path)
    s.agent.messages.append(Message.user("이전 대화"))
    s.agent.messages.append(Message.assistant("응답"))
    s.handle_slash("/clear")
    assert len(s.agent.messages) == 1
    assert s.agent.messages[0].role == "system"


def test_rebuild_는_대화_유지(tmp_path: Path) -> None:
    s = _session(tmp_path)
    s.agent.messages.append(Message.user("질문1"))
    s.rebuild(keep_history=True)
    roles = [m.role for m in s.agent.messages]
    assert roles == ["system", "user"]


def test_턴_실행_후_대화가_누적(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    backend = ScriptedBackend(
        [
            tool_response("read_file", {"path": "a.txt"}),
            text_response("hi 입니다"),
            text_response("두 번째 답"),
        ]
    )
    s = _session(tmp_path, backend=backend)
    from gigachanie.commands.chat import _run_turn

    run_sync(_run_turn(s, "a.txt 뭐야"))
    run_sync(_run_turn(s, "고마워"))
    users = [m.content for m in s.agent.messages if m.role == "user"]
    assert "a.txt 뭐야" in users and "고마워" in users

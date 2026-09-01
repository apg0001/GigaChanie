"""UX 마감: giga agent --json, chat 누적 토큰."""

import json
from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response

from gigachanie.commands.chat import ChatSession, _run_turn
from gigachanie.loop.approval import ApprovalMode
from gigachanie.serving.base import Usage, run_sync


def _sess(tmp_path: Path, backend) -> ChatSession:
    return ChatSession(
        backend,
        tmp_path,
        mode=ApprovalMode.SUGGEST,
        writable=False,
        max_steps=20,
        temperature=0.0,
        use_context=False,
        use_map=False,
    )


def test_chat_누적_토큰(tmp_path: Path) -> None:
    def resp(text: str):
        r = text_response(text)
        r.usage = Usage(prompt_tokens=10, completion_tokens=5)
        return r

    s = _sess(tmp_path, ScriptedBackend([resp("답1"), resp("답2")]))
    run_sync(_run_turn(s, "q1"))
    run_sync(_run_turn(s, "q2"))
    assert s.usage_prompt == 20
    assert s.usage_completion == 10


def test_agent_json_출력(tmp_path: Path, capsys) -> None:
    # git repo 초기화 (changed_files 계산용)
    import subprocess

    from typer.testing import CliRunner

    from gigachanie.cli import app

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    runner = CliRunner()
    import gigachanie.commands.agent as amod

    monkey = ScriptedBackend([tool_response("read_file", {"path": "x"}), text_response("완료")])
    (tmp_path / "x").write_text("hi", encoding="utf-8")

    orig = amod.build_backend
    amod.build_backend = lambda *a, **k: monkey  # type: ignore[assignment]
    try:
        result = runner.invoke(
            app, ["agent", "--json", "-C", str(tmp_path), "이거", "해줘"]
        )
    finally:
        amod.build_backend = orig  # type: ignore[assignment]

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["stop_reason"] == "done"
    assert "tokens" in data and "changed_files" in data

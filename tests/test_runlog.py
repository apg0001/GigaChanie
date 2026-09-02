"""실행 로그(runlog) 테스트."""

import json
from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.loop.agent import Agent
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.runlog import RunLogger, git_changed_files
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import run_sync

runner = CliRunner()


def _run_agent(tmp_path: Path, backend: ScriptedBackend) -> RunLogger:
    ctx = ToolContext(root=tmp_path)
    from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy

    ctx.policy = ApprovalPolicy(mode=ApprovalMode.FULL_AUTO)
    agent = Agent(backend, build_registry(writable=True), ctx)
    log = RunLogger(tmp_path, task="테스트 작업", model="test-model")
    result = run_sync(agent.run("뭔가 해줘", on_event=log.observe))
    log.finish(result, changed_files=git_changed_files(tmp_path))
    return log


def test_runlog_한줄_기록(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response("write_file", {"path": "a.txt", "content": "hi"}),
            text_response("완료했습니다."),
        ]
    )
    _run_agent(tmp_path, backend)

    path = tmp_path / ".agent" / "logs" / "runs.jsonl"
    assert path.is_file()
    rows = [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "테스트 작업"
    assert row["model"] == "test-model"
    assert row["ok"] is True
    assert row["stop_reason"] == "done"
    assert row["tools"]["write_file"] == 1
    assert "seconds" in row


def test_runlog_여러번_append(tmp_path: Path) -> None:
    for _ in range(3):
        backend = ScriptedBackend([text_response("끝")])
        _run_agent(tmp_path, backend)
    path = tmp_path / ".agent" / "logs" / "runs.jsonl"
    rows = path.read_text("utf-8").strip().splitlines()
    assert len(rows) == 3


def test_runlog_편집실패_카운트(tmp_path: Path) -> None:
    backend = ScriptedBackend(
        [
            tool_response("apply_edit", {"path": "none.txt", "search": "x", "replace": "y"}),
            text_response("실패"),
        ]
    )
    _run_agent(tmp_path, backend)
    row = json.loads(
        (tmp_path / ".agent" / "logs" / "runs.jsonl").read_text("utf-8").splitlines()[0]
    )
    assert row["edit_failures"] == 1


def test_runlog_cli_표시(tmp_path: Path) -> None:
    backend = ScriptedBackend([text_response("끝")])
    _run_agent(tmp_path, backend)

    res = runner.invoke(app, ["runlog", "-C", str(tmp_path)])
    assert res.exit_code == 0
    assert "test-model" in res.stdout

    res = runner.invoke(app, ["runlog", "-C", str(tmp_path), "--stats"])
    assert res.exit_code == 0
    assert "실행 1건" in res.stdout


def test_runlog_cli_로그없음(tmp_path: Path) -> None:
    res = runner.invoke(app, ["runlog", "-C", str(tmp_path)])
    assert res.exit_code == 0
    assert "실행 로그가 없습니다" in res.stdout

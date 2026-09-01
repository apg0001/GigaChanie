"""편집 체크포인트 / undo 테스트."""

from pathlib import Path

from conftest import ScriptedBackend, text_response, tool_response
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.loop.agent import Agent
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.checkpoint import CheckpointStore
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import run_sync

runner = CliRunner()


def _ctx(root: Path, store: CheckpointStore) -> ToolContext:
    return ToolContext(
        root=root,
        policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO),
        checkpoints=store,
    )


def test_수정_스냅샷_후_undo(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("원본\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    store.open_turn("a.py 수정")

    tool = build_registry(writable=True).get("write_file")
    assert tool is not None
    run_sync(tool.run({"path": "a.py", "content": "수정됨\n"}, _ctx(tmp_path, store)))
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "수정됨\n"
    store.close_turn()

    label, restored = store.undo()
    assert label == "a.py 수정"
    assert "a.py" in restored
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "원본\n"


def test_새파일_undo는_삭제(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.open_turn("새 파일")
    tool = build_registry(writable=True).get("write_file")
    run_sync(tool.run({"path": "new.py", "content": "x\n"}, _ctx(tmp_path, store)))
    store.close_turn()

    store.undo()
    assert not (tmp_path / "new.py").exists()


def test_한_턴에_여러파일_첫_상태만_스냅샷(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    store.open_turn("연속 수정")
    ctx = _ctx(tmp_path, store)
    tool = build_registry(writable=True).get("write_file")
    run_sync(tool.run({"path": "a.py", "content": "v2\n"}, ctx))
    run_sync(tool.run({"path": "a.py", "content": "v3\n"}, ctx))
    store.close_turn()

    store.undo()
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"


def test_undo_이력_없으면_None(tmp_path: Path) -> None:
    assert CheckpointStore(tmp_path).undo() is None


def test_agent_run_이_턴을_기록(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    backend = ScriptedBackend(
        [
            tool_response(
                "apply_edit",
                {"path": "m.py", "search": "    return 1", "replace": "    return 2"},
            ),
            text_response("고쳤습니다."),
        ]
    )
    agent = Agent(backend, build_registry(writable=True), _ctx(tmp_path, store))
    run_sync(agent.run("m.py 고쳐줘"))
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"

    label, restored = store.undo()
    assert "m.py 고쳐줘" in label
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"


def test_giga_undo_cli(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("before\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    store.open_turn("변경")
    store.before_write(tmp_path / "a.txt")
    (tmp_path / "a.txt").write_text("after\n", encoding="utf-8")
    store.close_turn()

    lst = runner.invoke(app, ["undo", "--list", "-C", str(tmp_path)])
    assert lst.exit_code == 0 and "변경" in lst.stdout

    res = runner.invoke(app, ["undo", "-C", str(tmp_path)])
    assert res.exit_code == 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "before\n"

    again = runner.invoke(app, ["undo", "-C", str(tmp_path)])
    assert again.exit_code == 1

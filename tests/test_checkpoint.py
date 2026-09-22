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


def test_current_files_열린_턴의_파일만(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    assert store.current_files() == []  # 턴 시작 전엔 빈 목록

    store.open_turn("작업")
    store.before_write(tmp_path / "a.py")
    store.before_write(tmp_path / "b.py")
    assert sorted(store.current_files()) == ["a.py", "b.py"]

    store.close_turn()
    assert store.current_files() == []  # 턴이 닫히면 다시 빈 목록(_current=None)


def test_agent_last_changed_files는_턴마다_새로_시작한다(tmp_path: Path) -> None:
    """git diff HEAD 는 커밋 안 하고 여러 턴을 거치면 이전 턴 파일까지 계속
    섞여 나온다. 체크포인트 기반은 턴마다 정확히 그 턴의 파일만 보여줘야 한다."""
    store = CheckpointStore(tmp_path)
    ctx = _ctx(tmp_path, store)
    backend = ScriptedBackend(
        [
            tool_response("write_file", {"path": "a.py", "content": "a"}),
            text_response("a 완료"),
            tool_response("write_file", {"path": "b.py", "content": "b"}),
            text_response("b 완료"),
        ]
    )
    agent = Agent(backend, build_registry(writable=True), ctx)

    run_sync(agent.run("a.py 만들어"))
    assert agent.last_changed_files == ["a.py"]

    run_sync(agent.run("b.py 도 만들어"))
    assert agent.last_changed_files == ["b.py"]  # a.py 는 다시 안 나옴


def test_resolve_changed_files_체크포인트_없으면_git으로_폴백(tmp_path: Path) -> None:
    import subprocess

    from gigachanie.loop.runlog import resolve_changed_files

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "existing.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "existing.txt").write_text("y\n", encoding="utf-8")

    # 체크포인트 비활성(readonly 세션 등) → last_changed_files 는 None → git 폴백
    agent = Agent(
        ScriptedBackend([]), build_registry(writable=True), ToolContext(root=tmp_path)
    )
    assert agent.last_changed_files is None
    assert "existing.txt" in resolve_changed_files(agent, tmp_path)


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

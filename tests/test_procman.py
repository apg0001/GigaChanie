"""백그라운드 프로세스 관리 테스트."""

import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.procman import ProcessManager
from gigachanie.loop.tools import ToolContext, ToolError
from gigachanie.serving.base import run_sync

runner = CliRunner()

PY = sys.executable


def _ctx(root: Path, pm: ProcessManager) -> ToolContext:
    return ToolContext(
        root=root, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO), procman=pm
    )


def test_start_tail_stop(tmp_path: Path) -> None:
    pm = ProcessManager(tmp_path)
    script = (
        "import time\n"
        "for i in range(50):\n"
        "    print('tick', i, flush=True); time.sleep(0.2)\n"
    )
    (tmp_path / "s.py").write_text(script, encoding="utf-8")
    h = pm.start(f"{PY} s.py")
    try:
        assert h.alive()
        ok, _ = pm.wait_for(h.id, r"tick", timeout=10)
        assert ok, pm.tail(h.id)
        assert "tick" in pm.tail(h.id, lines=10)
        assert any(p.id == h.id for p in pm.list())
    finally:
        assert pm.stop(h.id) is True
    time.sleep(0.3)
    assert not h.alive()
    assert pm.list() == []


def test_wait_for_log(tmp_path: Path) -> None:
    pm = ProcessManager(tmp_path)
    (tmp_path / "srv.py").write_text(
        "import time\ntime.sleep(0.4)\nprint('Listening on 8000', flush=True)\ntime.sleep(3)\n",
        encoding="utf-8",
    )
    h = pm.start(f"{PY} srv.py")
    try:
        ok, _ = pm.wait_for(h.id, r"Listening on \d+", timeout=5)
        assert ok
        bad, _ = pm.wait_for(h.id, "존재하지않는패턴", timeout=1)
        assert not bad
    finally:
        pm.stop(h.id)


def test_proc_도구들(tmp_path: Path) -> None:
    pm = ProcessManager(tmp_path)
    ctx = _ctx(tmp_path, pm)
    reg = build_registry(writable=True)
    (tmp_path / "loop.py").write_text(
        "import time\nwhile True:\n    print('alive', flush=True); time.sleep(0.3)\n",
        encoding="utf-8",
    )
    try:
        start = run_sync(reg.get("run_background").run({"command": f"{PY} loop.py"}, ctx))
        assert not start.is_error
        pid_line = start.content
        proc_id = pid_line.split("id=")[1].split()[0]

        ok, _ = pm.wait_for(proc_id, r"alive", timeout=10)
        assert ok
        tail = run_sync(reg.get("tail_logs").run({"id": proc_id}, ctx))
        assert "alive" in tail.content

        lst = run_sync(reg.get("list_processes").run({}, ctx))
        assert proc_id in lst.content

        stop = run_sync(reg.get("stop_process").run({"id": proc_id}, ctx))
        assert not stop.is_error
    finally:
        pm.stop_all()


def test_procman_없으면_도구_오류(tmp_path: Path) -> None:
    ctx = ToolContext(root=tmp_path, policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO))
    reg = build_registry(writable=True)
    # 에이전트 루프는 ToolError 를 잡아 모델 피드백으로 변환한다.
    with pytest.raises(ToolError):
        run_sync(reg.get("list_processes").run({}, ctx))


def test_giga_ps_kill_cli(tmp_path: Path) -> None:
    pm = ProcessManager(tmp_path)
    (tmp_path / "w.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    h = pm.start(f"{PY} w.py")
    try:
        out = runner.invoke(app, ["ps", "-C", str(tmp_path)])
        assert out.exit_code == 0 and h.id in out.stdout

        k = runner.invoke(app, ["kill", h.id, "-C", str(tmp_path)])
        assert k.exit_code == 0
        assert runner.invoke(app, ["kill", h.id, "-C", str(tmp_path)]).exit_code == 1
    finally:
        pm.stop_all()

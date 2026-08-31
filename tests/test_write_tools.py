"""쓰기/실행 도구 테스트."""

import sys
from pathlib import Path

from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import run_sync


def _ctx(root: Path, *, allow: bool = True) -> ToolContext:
    pol = ApprovalPolicy(
        mode=ApprovalMode.SUGGEST,
        approver=(lambda _r: allow),
    )
    return ToolContext(root=root, policy=pol)


def _run(name: str, args: dict, ctx: ToolContext):
    tool = build_registry(writable=True).get(name)
    assert tool is not None
    return run_sync(tool.run(args, ctx))


def test_write_file_새파일_생성(tmp_path: Path) -> None:
    res = _run("write_file", {"path": "pkg/new.py", "content": "x = 1\n"}, _ctx(tmp_path))
    assert not res.is_error
    assert (tmp_path / "pkg" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


def test_write_file_승인_거부(tmp_path: Path) -> None:
    res = _run(
        "write_file",
        {"path": "a.py", "content": "y = 2\n"},
        _ctx(tmp_path, allow=False),
    )
    assert res.is_error
    assert "거부" in res.content
    assert not (tmp_path / "a.py").exists()


def test_write_file_변경없음(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("same\n", encoding="utf-8")
    res = _run("write_file", {"path": "a.py", "content": "same\n"}, _ctx(tmp_path))
    assert "변경 없음" in res.content


def test_run_shell_기본_명령(tmp_path: Path) -> None:
    # 허용 목록에 없는 명령 → approver=True 로 승인
    res = _run("run_shell", {"command": f'{sys.executable} -c "print(123)"'}, _ctx(tmp_path))
    assert "123" in res.content
    assert "[종료코드 0]" in res.content


def test_run_shell_거부목록_차단(tmp_path: Path) -> None:
    res = _run("run_shell", {"command": "rm -rf /"}, _ctx(tmp_path))
    assert res.is_error
    assert "거부" in res.content


def test_run_shell_비정상_종료코드(tmp_path: Path) -> None:
    res = _run(
        "run_shell",
        {"command": f'{sys.executable} -c "import sys; sys.exit(3)"'},
        _ctx(tmp_path),
    )
    assert res.is_error
    assert "[종료코드 3]" in res.content


def test_run_shell_타임아웃(tmp_path: Path) -> None:
    res = _run(
        "run_shell",
        {"command": f'{sys.executable} -c "import time; time.sleep(5)"', "timeout": 1},
        _ctx(tmp_path),
    )
    assert res.is_error
    assert "시간 초과" in res.content

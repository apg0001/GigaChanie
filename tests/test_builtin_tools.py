"""읽기 전용 기본 도구 테스트."""

from pathlib import Path

import pytest

from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.tools import ToolContext, ToolError
from gigachanie.serving.base import run_sync


def _run(name: str, args: dict, root: Path):
    reg = default_readonly_registry()
    tool = reg.get(name)
    assert tool is not None
    return run_sync(tool.run(args, ToolContext(root=root)))


def _sample_tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (root / "src" / "util.py").write_text("# TODO: 리팩터\nX = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# 샘플\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("ignored", encoding="utf-8")


def test_list_dir(tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    res = _run("list_dir", {"path": "."}, tmp_path)
    assert "src/" in res.content
    assert "README.md" in res.content
    assert ".git" not in res.content


def test_read_file_행번호_및_범위(tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    res = _run("read_file", {"path": "src/main.py"}, tmp_path)
    assert "1\tdef hello():" in res.content
    ranged = _run("read_file", {"path": "src/main.py", "start_line": 2, "end_line": 2}, tmp_path)
    assert "return 'hi'" in ranged.content
    assert "def hello" not in ranged.content


def test_read_file_없는파일(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        _run("read_file", {"path": "nope.py"}, tmp_path)


def test_glob(tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    res = _run("glob", {"pattern": "**/*.py"}, tmp_path)
    assert "src/main.py" in res.content
    assert "src/util.py" in res.content
    assert "README.md" not in res.content


def test_grep(tmp_path: Path) -> None:
    _sample_tree(tmp_path)
    res = _run("grep", {"pattern": "TODO", "glob": "*.py"}, tmp_path)
    assert "src/util.py:1" in res.content
    none = _run("grep", {"pattern": "존재하지않는패턴XYZ"}, tmp_path)
    assert "일치 없음" in none.content


def test_grep_ripgrep_사용(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from gigachanie.loop import builtin_tools as bt

    _sample_tree(tmp_path)
    monkeypatch.setattr(bt.shutil, "which", lambda name: "/usr/bin/rg" if name == "rg" else None)

    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return subprocess.CompletedProcess(
            argv, 0, stdout="src/util.py:1:# TODO: 리팩터\n", stderr=""
        )

    monkeypatch.setattr(bt.subprocess, "run", fake_run)
    res = _run("grep", {"pattern": "TODO"}, tmp_path)
    assert captured["argv"][0] == "/usr/bin/rg"
    assert "src/util.py:1" in res.content


def test_경로_탈출_차단(tmp_path: Path) -> None:
    (tmp_path / "inside").mkdir()
    ctx = ToolContext(root=tmp_path / "inside")
    with pytest.raises(ToolError):
        ctx.resolve("../../etc/passwd")

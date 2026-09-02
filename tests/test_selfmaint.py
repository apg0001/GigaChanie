"""자기 점검·업데이트(selfmaint) 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gigachanie import selfmaint
from gigachanie.cli import app

runner = CliRunner()


def test_detect_install_이_저장소는_editable() -> None:
    inst = selfmaint.detect_install()
    assert inst.method in ("editable", "pip", "pipx")
    # 이 테스트는 소스 체크아웃에서 돌므로 repo_root 가 잡혀야 한다.
    assert inst.repo_root is not None
    assert (inst.repo_root / "pyproject.toml").is_file()
    assert inst.can_self_fix


def test_vtuple_비교() -> None:
    assert selfmaint._vtuple("1.2.3") == (1, 2, 3)
    assert selfmaint._vtuple("0.10.0") > selfmaint._vtuple("0.9.9")
    assert selfmaint._vtuple("v2.0") == (2, 0)


def test_update_command_설치방식별(tmp_path: Path) -> None:
    git_repo = selfmaint.InstallInfo("0.0.1", "editable", None, tmp_path, True)
    assert selfmaint.update_command(git_repo)[:2] == ["git", "-C"]

    no_git = selfmaint.InstallInfo("0.0.1", "editable", None, tmp_path, False)
    assert selfmaint.update_command(no_git) == []

    pipx = selfmaint.InstallInfo("0.0.1", "pipx", None, None, False)
    assert selfmaint.update_command(pipx) == ["pipx", "upgrade", "gigachanie"]

    pip = selfmaint.InstallInfo("0.0.1", "pip", None, None, False)
    assert selfmaint.update_command(pip)[1:] == [
        "-m",
        "pip",
        "install",
        "-U",
        "gigachanie",
    ]


def test_check_update_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfmaint, "__version__", "0.0.1")
    monkeypatch.setattr(selfmaint, "latest_version", lambda **_: "9.9.9")
    status = selfmaint.check_update()
    assert status.behind and status.latest == "9.9.9"

    monkeypatch.setattr(selfmaint, "latest_version", lambda **_: None)
    assert selfmaint.check_update().behind is False


def test_latest_version_네트워크실패시_None(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def boom(*_a, **_k):
        raise httpx.ConnectError("no net")

    monkeypatch.setattr(httpx, "get", boom)
    assert selfmaint.latest_version(timeout=0.1) is None


def test_self_fix_argv_구조(tmp_path: Path) -> None:
    argv = selfmaint.self_fix_argv(tmp_path, "버그 고쳐", yolo=False)
    assert argv[0] == sys.executable
    assert argv[1:5] == ["-m", "gigachanie", "agent", "-C"]
    assert "--web" in argv and "--write" in argv
    assert argv[-1].startswith(selfmaint.SELF_FIX_PREAMBLE)
    assert argv[-1].endswith("버그 고쳐")

    yolo = selfmaint.self_fix_argv(tmp_path, "x", yolo=True)
    assert "--yolo" in yolo and "--write" not in yolo


def test_run_diagnostics_안깨짐() -> None:
    assert isinstance(selfmaint.run_diagnostics(), list)


def test_cli_self_info_offline() -> None:
    res = runner.invoke(app, ["self", "info", "--offline"])
    assert res.exit_code == 0
    assert "editable" in res.stdout


def test_cli_self_update_dry_run() -> None:
    res = runner.invoke(app, ["self", "update", "--dry-run"])
    assert res.exit_code == 0
    assert "git" in res.stdout or "pip" in res.stdout


def test_cli_self_fix_show() -> None:
    res = runner.invoke(app, ["self", "fix", "--show", "테스트", "고쳐"])
    assert res.exit_code == 0
    assert "agent" in res.stdout and "테스트 고쳐" in res.stdout

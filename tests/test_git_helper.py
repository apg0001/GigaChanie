"""giga commit / giga pr 테스트."""

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.commands import git as gitmod

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / "AGENTS.md").write_text(
        "## git 규칙\n- 커밋 제목은 [feat] 형식\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_commit_스테이지_없으면_오류(tmp_path: Path) -> None:
    _repo(tmp_path)
    result = runner.invoke(app, ["commit", "-C", str(tmp_path)])
    assert result.exit_code == 1
    assert "스테이지된 변경이 없습니다" in result.stdout


def _log(tmp_path: Path, fmt: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", f"--pretty={fmt}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def test_commit_직접메시지(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(
        app, ["commit", "-C", str(tmp_path), "-a", "-m", "[feat] a 추가", "-y"]
    )
    assert result.exit_code == 0
    assert _log(tmp_path, "%s") == "[feat] a 추가"


def test_commit_모델생성(tmp_path: Path, monkeypatch) -> None:
    _repo(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")

    from conftest import ScriptedBackend, text_response

    def fake_build(*_a, **_k):
        return ScriptedBackend([text_response("[feat] b 모듈 추가\n\n- b.py 생성")])

    monkeypatch.setattr(gitmod, "build_backend", fake_build)
    result = runner.invoke(app, ["commit", "-C", str(tmp_path), "-a", "-y"])
    assert result.exit_code == 0
    assert "[feat] b 모듈 추가" in _log(tmp_path, "%B")


def test_git_rules_추출(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# 개요\n본문\n\n## git 작업 규칙\n- 규칙1\n- 규칙2\n", encoding="utf-8"
    )
    rules = gitmod._git_rules(tmp_path)
    assert "규칙1" in rules and "git 작업 규칙" in rules


def test_pr_커밋없으면_오류(tmp_path: Path) -> None:
    _repo(tmp_path)
    result = runner.invoke(app, ["pr", "-C", str(tmp_path), "--base", "HEAD"])
    assert result.exit_code == 1

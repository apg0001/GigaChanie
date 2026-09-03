"""재사용 지시문(`.agent/prompts/`) 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ScriptedBackend, text_response
from typer.testing import CliRunner

import gigachanie.commands.agent as amod
from gigachanie.cli import app
from gigachanie.context import list_prompts, load_prompts
from gigachanie.context import prompts as pmod

runner = CliRunner()


def _mk(root: Path, name: str, body: str) -> None:
    d = root / ".agent" / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body, encoding="utf-8")


def test_load_prompts_합치기(tmp_path: Path) -> None:
    _mk(tmp_path, "style", "간결하게 써라.")
    _mk(tmp_path, "kr", "한국어로 답하라.")
    text, missing = load_prompts(tmp_path, ["style", "kr", "none"])
    assert "간결하게 써라." in text and "한국어로 답하라." in text
    assert missing == ["none"]


def test_list_prompts(tmp_path: Path) -> None:
    _mk(tmp_path, "a", "aaa")
    assert [p.name for p in list_prompts(tmp_path)] == ["a"]


def test_프로젝트가_사용자_덮어씀(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = tmp_path / "usercfg"
    (user / "prompts").mkdir(parents=True)
    (user / "prompts" / "x.md").write_text("사용자 버전", encoding="utf-8")
    monkeypatch.setattr(pmod, "user_config_path", lambda *a, **k: user)
    _mk(tmp_path, "x", "프로젝트 버전")
    text, _ = load_prompts(tmp_path, ["x"])
    assert text == "프로젝트 버전"


def test_cli_prompts_목록(tmp_path: Path) -> None:
    _mk(tmp_path, "style", "간결하게.")
    res = runner.invoke(app, ["prompts", "-C", str(tmp_path)])
    assert res.exit_code == 0 and "style" in res.stdout

    res = runner.invoke(app, ["prompts", "-C", str(tmp_path), "--show", "style"])
    assert "간결하게." in res.stdout


def test_agent_p_옵션이_시스템프롬프트에_주입(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _mk(tmp_path, "rule", "SENTINEL_규칙_지문")
    backend = ScriptedBackend([text_response("끝")])
    monkeypatch.setattr(amod, "build_backend", lambda *a, **k: backend)

    res = runner.invoke(
        app,
        ["agent", "-C", str(tmp_path), "--no-context", "--no-map", "-p", "rule", "일해"],
    )
    assert res.exit_code == 0
    sys_msg = backend.received[0][0]
    assert sys_msg.role == "system" and "SENTINEL_규칙_지문" in sys_msg.content

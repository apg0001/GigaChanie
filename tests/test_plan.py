"""`giga plan` 계획 모드 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ScriptedBackend, text_response, tool_response
from typer.testing import CliRunner

import gigachanie.commands.plan as pmod
from gigachanie.cli import app

runner = CliRunner()


def _patch(monkeypatch: pytest.MonkeyPatch, backend: ScriptedBackend) -> None:
    monkeypatch.setattr(pmod, "build_backend", lambda *a, **k: backend)


def test_plan_계획_출력(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _patch(
        monkeypatch,
        ScriptedBackend(
            [
                tool_response("read_file", {"path": "a.py"}),
                text_response("1. `a.py` — x 를 2 로 바꾼다\n확인 필요: 없음\n위험: 없음"),
            ]
        ),
    )
    res = runner.invoke(
        app, ["plan", "-C", str(tmp_path), "--no-context", "--no-map", "a.py 고쳐"]
    )
    assert res.exit_code == 0
    assert "계획" in res.stdout
    assert "x 를 2 로" in res.stdout
    # 파일은 그대로
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_plan_쓰기도구_없음(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(
        monkeypatch,
        ScriptedBackend(
            [
                tool_response("write_file", {"path": "z.py", "content": "bad"}),
                text_response("계획: z.py 생성"),
            ]
        ),
    )
    res = runner.invoke(
        app, ["plan", "-C", str(tmp_path), "--no-context", "--no-map", "만들어"]
    )
    assert res.exit_code == 0
    assert not (tmp_path / "z.py").exists()


def test_plan_비대화_x_는_실행안함(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch(monkeypatch, ScriptedBackend([text_response("1. 아무것도 안 함")]))
    called = []
    monkeypatch.setattr(pmod.subprocess, "run", lambda *a, **k: called.append(a))
    res = runner.invoke(
        app, ["plan", "-C", str(tmp_path), "--no-context", "--no-map", "-x", "뭔가"]
    )
    assert res.exit_code == 0
    assert called == []
    assert "비대화" in res.stdout

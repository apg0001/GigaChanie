"""앙상블(여러 모델 병렬 + 판정) 테스트."""

from __future__ import annotations

import pytest
from conftest import ScriptedBackend, text_response
from typer.testing import CliRunner

import gigachanie.commands.ensemble as emod
from gigachanie.cli import app
from gigachanie.orchestra.ensemble import run_ensemble
from gigachanie.serving.base import run_sync

runner = CliRunner()


def test_run_ensemble_종합() -> None:
    m1 = ("a", ScriptedBackend([text_response("A: 답은 42")]))
    m2 = ("b", ScriptedBackend([text_response("B: 답은 43")]))
    judge = ("j", ScriptedBackend([text_response("종합: 42 가 맞다")]))

    result = run_sync(run_ensemble("답이 뭐야?", [m1, m2], judge))
    assert len(result.answers) == 2
    assert result.answers[0] == ("a", "A: 답은 42")
    assert "42 가 맞다" in result.verdict
    assert m1[1].closed and judge[1].closed


def test_판정_프롬프트에_후보가_들어감() -> None:
    j = ScriptedBackend([text_response("ok")])
    run_sync(
        run_ensemble(
            "Q",
            [("a", ScriptedBackend([text_response("cand-A")]))],
            ("j", j),
        )
    )
    judge_input = j.received[0][-1].content
    assert "cand-A" in judge_input and "Q" in judge_input


def test_cli_모델_부족(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(emod, "default_specs", lambda root: [])
    res = runner.invoke(app, ["ensemble", "-C", str(tmp_path), "질문"])
    assert res.exit_code == 2
    assert "2개 이상" in res.stdout


def test_cli_동작(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def fake_resolve(spec: str, root):
        return spec, ScriptedBackend([text_response(f"{spec} 의 답")])

    monkeypatch.setattr(emod, "resolve_backend", fake_resolve)
    res = runner.invoke(
        app, ["ensemble", "-C", str(tmp_path), "-m", "x", "-m", "y", "질문"]
    )
    assert res.exit_code == 0
    assert "종합" in res.stdout

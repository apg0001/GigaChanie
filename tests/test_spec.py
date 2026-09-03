"""스펙 협업(giga spec) 테스트."""

from __future__ import annotations

import pytest
from conftest import ScriptedBackend, text_response
from typer.testing import CliRunner

import gigachanie.commands.spec as smod
from gigachanie.cli import app
from gigachanie.orchestra.spec import collaborate
from gigachanie.serving.base import run_sync

runner = CliRunner()


def test_collaborate_초안후검증() -> None:
    drafter = ScriptedBackend([text_response("## 목표\n초안입니다")])
    reviewer = ScriptedBackend([text_response("## 리뷰 노트\n좋음\n## 최종본\n다듬은 버전")])
    result = run_sync(collaborate("로그인 기능", drafter, reviewer))
    assert result.draft == "## 목표\n초안입니다"
    assert "다듬은 버전" in result.final
    assert drafter.closed and reviewer.closed
    # 검증 프롬프트에 초안이 포함됨
    assert "초안입니다" in reviewer.received[0][-1].content


def test_cli_출력_및_저장(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    seq = [
        ScriptedBackend([text_response("초안 본문")]),
        ScriptedBackend([text_response("## 최종본\n최종 본문")]),
    ]
    calls = iter(seq)
    monkeypatch.setattr(smod, "build_backend", lambda **k: next(calls))
    out = tmp_path / "spec.md"
    res = runner.invoke(
        app, ["spec", "-C", str(tmp_path), "-o", str(out), "--show-draft", "요구사항"]
    )
    assert res.exit_code == 0
    assert "초안 본문" in res.stdout and "최종 본문" in res.stdout
    assert out.read_text(encoding="utf-8").strip() == "## 최종본\n최종 본문"

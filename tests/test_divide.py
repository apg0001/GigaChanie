"""작업 분할(giga divide) 테스트."""

from __future__ import annotations

import pytest
from conftest import ScriptedBackend, text_response
from typer.testing import CliRunner

import gigachanie.commands.divide as dmod
from gigachanie.cli import app
from gigachanie.orchestra.divide import plan_subtasks
from gigachanie.serving.base import run_sync

runner = CliRunner()


def test_plan_subtasks_파싱() -> None:
    backend = ScriptedBackend(
        [
            text_response(
                "1. `a.py` 에 함수 추가\n"
                "- `b.py` 임포트 정리\n"
                "테스트 작성\n"
                "\n"
            )
        ]
    )
    items = run_sync(plan_subtasks(backend, "목표"))
    assert items == ["`a.py` 에 함수 추가", "`b.py` 임포트 정리", "테스트 작성"]


def test_plan_subtasks_최대개수() -> None:
    backend = ScriptedBackend([text_response("\n".join(f"작업{i}" for i in range(10)))])
    assert len(run_sync(plan_subtasks(backend, "x", max_items=4))) == 4


def test_cli_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        dmod, "build_backend", lambda **k: ScriptedBackend([text_response("단계 하나\n단계 둘")])
    )
    res = runner.invoke(
        app, ["divide", "-C", str(tmp_path), "--dry-run", "리팩터해"]
    )
    assert res.exit_code == 0
    assert "단계 하나" in res.stdout and "단계 둘" in res.stdout


def test_cli_비대화_y없으면_실행안함(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        dmod, "build_backend", lambda **k: ScriptedBackend([text_response("단계 하나")])
    )
    calls = []
    monkeypatch.setattr(dmod.subprocess, "run", lambda *a, **k: calls.append(a))
    res = runner.invoke(app, ["divide", "-C", str(tmp_path), "리팩터해"])
    assert res.exit_code == 0
    assert calls == []
    assert "-y" in res.stdout

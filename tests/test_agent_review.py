"""`giga agent --review` 파이프라인의 diff 수집 테스트."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import ScriptedBackend, text_response

from gigachanie.commands.agent import _full_diff_including_new_files, _pipeline_review
from gigachanie.loop.agent import Agent
from gigachanie.loop.builtin_tools import default_readonly_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import run_sync


def _git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "existing.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)


def test_새파일만_만들어도_diff에_잡힌다(tmp_path: Path) -> None:
    """git diff HEAD 만 보면 커밋 안 된 새 파일은 안 보여서 리뷰가
    '변경 없음' 으로 조용히 건너뛰어졌다 — 정작 새 파일은 검토가 필요한데."""
    _git_repo(tmp_path)
    (tmp_path / "brandnew.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    diff = _full_diff_including_new_files(tmp_path)
    assert "brandnew.py" in diff
    assert "def f()" in diff
    assert "new file mode" in diff


def test_기존파일_수정도_그대로_포함된다(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / "existing.py").write_text("x = 2\n", encoding="utf-8")

    diff = _full_diff_including_new_files(tmp_path)
    assert "existing.py" in diff
    assert "-x = 1" in diff and "+x = 2" in diff


def test_변경없으면_빈문자열(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    assert _full_diff_including_new_files(tmp_path) == ""


def test_pipeline_review가_새파일도_리뷰모델에_보낸다(tmp_path: Path) -> None:
    """_pipeline_review 가 새 파일만 있어도 리뷰를 건너뛰지 않고 실제로
    검토 모델을 호출하는지(= '변경 없음' 으로 조기 종료하지 않는지) 확인."""
    _git_repo(tmp_path)
    (tmp_path / "brandnew.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    review_backend = ScriptedBackend([text_response("문제 없음")])
    agent_backend = ScriptedBackend([])
    ag = Agent(agent_backend, default_readonly_registry(), ToolContext(root=tmp_path))
    ag.backend = review_backend  # 리뷰 전용 모델(pl.review_ref) 미설정 시 ag.backend 를 씀

    run_sync(_pipeline_review(ag, tmp_path, "새 파일 추가", apply_fix=False))

    assert review_backend.received  # 실제로 chat() 이 호출됨
    sent = review_backend.received[0][-1].content
    assert "brandnew.py" in sent

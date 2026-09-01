"""대화형 선택 UI + '항상 허용' 규칙 저장 테스트."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.commands._agentui import _remember_rule
from gigachanie.commands._pick import pick
from gigachanie.loop.approval import ApprovalRequest

runner = CliRunner()


def test_pick_비대화면_None() -> None:
    # CliRunner/파이프 환경 = 비 TTY → None
    assert pick("고르세요", [("A", "a"), ("B", "b")]) is None
    assert pick("빈 목록", []) is None


def test_model_use_인자없이_비대화면_취소(tmp_path, monkeypatch) -> None:
    import gigachanie.config as cfgmod

    monkeypatch.setattr(cfgmod, "_USER_CONFIG", tmp_path / "config.yaml")
    result = runner.invoke(app, ["model", "use"])
    assert result.exit_code == 1
    assert "취소" in result.stdout


def test_doctor_use_비대화면_선택없음(tmp_path, monkeypatch) -> None:
    import gigachanie.config as cfgmod

    monkeypatch.setattr(cfgmod, "_USER_CONFIG", tmp_path / "config.yaml")
    result = runner.invoke(app, ["doctor", "--use"])
    # 진단은 정상 출력, 비대화라 선택은 건너뜀
    assert result.exit_code == 0
    assert "선택 안 함" in result.stdout


def test_remember_rule_쓰기_경로(tmp_path: Path) -> None:
    _remember_rule(
        tmp_path,
        ApprovalRequest(kind="write", summary="편집: src/mod/a.py", path="src/mod/a.py"),
    )
    pf = tmp_path / ".agent" / "permissions.yaml"
    data = yaml.safe_load(pf.read_text("utf-8"))
    assert "src/mod/**" in data["allow_paths"]


def test_remember_rule_셸_명령(tmp_path: Path) -> None:
    _remember_rule(
        tmp_path,
        ApprovalRequest(kind="shell", summary="셸 실행: npm run dev", detail="npm run dev"),
    )
    data = yaml.safe_load((tmp_path / ".agent" / "permissions.yaml").read_text("utf-8"))
    assert any("npm" in r for r in data["allow_shell"])


def test_remember_rule_중복_추가안함(tmp_path: Path) -> None:
    req = ApprovalRequest(kind="write", summary="", path="lib/x.py")
    _remember_rule(tmp_path, req)
    _remember_rule(tmp_path, req)
    data = yaml.safe_load((tmp_path / ".agent" / "permissions.yaml").read_text("utf-8"))
    assert data["allow_paths"].count("lib/**") == 1

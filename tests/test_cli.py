"""CLI 기본 동작 테스트."""

from typer.testing import CliRunner

from gigachanie import __version__
from gigachanie.cli import app

runner = CliRunner()


def test_버전_출력() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_도움말_출력() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "코딩 에이전트" in result.stdout


def test_doctor_실행() -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    assert '"hardware"' in result.stdout
    assert '"recommendations"' in result.stdout


def test_model_list_실행() -> None:
    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0
    assert "qwen" in result.stdout.lower()


def test_model_use_알수없는ID() -> None:
    result = runner.invoke(app, ["model", "use", "존재하지-않는-모델"])
    assert result.exit_code == 1

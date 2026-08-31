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


def test_hello_명령() -> None:
    result = runner.invoke(app, ["hello"])
    assert result.exit_code == 0

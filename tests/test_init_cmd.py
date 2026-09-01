"""`giga init` 테스트."""

from pathlib import Path

from typer.testing import CliRunner

from gigachanie.cli import app

runner = CliRunner()


def test_init_python_프로젝트(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\n[tool.ruff]\n[tool.pytest.ini_options]\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# 데모 프로젝트\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "-C", str(tmp_path)])
    assert result.exit_code == 0
    agents = tmp_path / "AGENTS.md"
    assert agents.is_file()
    body = agents.read_text(encoding="utf-8")
    assert "데모 프로젝트" in body
    assert "python -m pytest" in body
    assert "ruff check ." in body
    assert "Python" in body


def test_init_기존파일_보호(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("기존 내용", encoding="utf-8")
    result = runner.invoke(app, ["init", "-C", str(tmp_path)])
    assert result.exit_code == 1
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "기존 내용"

    forced = runner.invoke(app, ["init", "-C", str(tmp_path), "--force"])
    assert forced.exit_code == 0
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") != "기존 내용"


def test_init_show는_파일_안만듦(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "jest", "build": "tsc"}}', encoding="utf-8"
    )
    result = runner.invoke(app, ["init", "-C", str(tmp_path), "--show"])
    assert result.exit_code == 0
    assert not (tmp_path / "AGENTS.md").exists()
    assert "npm run test" in result.stdout

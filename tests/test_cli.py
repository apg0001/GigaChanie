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


def test_model_use_no_pull_은_설정만_저장(tmp_path, monkeypatch) -> None:
    import gigachanie.config as cfgmod

    monkeypatch.setattr(cfgmod, "_USER_CONFIG", tmp_path / "config.yaml")
    # 비대화 실행(CliRunner) + --no-pull → 다운로드 시도 없이 성공
    result = runner.invoke(
        app, ["model", "use", "qwen2.5-coder-7b-instruct", "--no-pull"]
    )
    assert result.exit_code == 0
    assert "선택됨" in result.stdout
    assert (tmp_path / "config.yaml").is_file()


def test_model_use_비대화_자동pull_시도(tmp_path, monkeypatch) -> None:
    import gigachanie.commands.model as modmod
    import gigachanie.config as cfgmod

    monkeypatch.setattr(cfgmod, "_USER_CONFIG", tmp_path / "config.yaml")
    called: list[str] = []
    monkeypatch.setattr(modmod, "_ollama_has", lambda _tag: False)
    monkeypatch.setattr(modmod, "_ollama_pull", lambda tag: called.append(tag) or 0)

    result = runner.invoke(app, ["model", "use", "qwen2.5-coder-7b-instruct"])
    assert result.exit_code == 0
    assert called == ["qwen2.5-coder:7b"]  # 자동으로 다운로드 시도

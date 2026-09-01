"""Ollama 자동 설치 흐름 테스트 (실제 설치는 하지 않음)."""

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.serving import ollama_setup

runner = CliRunner()


def test_ensure_ready_이미_준비됨(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: True)
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: True)
    ok, msg = ollama_setup.ensure_ready(auto=False, ask=False)
    assert ok and "준비" in msg


def test_ensure_ready_미설치_비대화_안내만(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: False)
    called = []
    monkeypatch.setattr(ollama_setup, "install", lambda: called.append(1) or (True, ""))
    ok, msg = ollama_setup.ensure_ready(auto=False, ask=False)
    assert not ok
    assert not called  # 동의 없이 설치 시도 안 함
    assert "giga setup" in msg


def test_ensure_ready_설치_진행(monkeypatch) -> None:
    state = {"installed": False}
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: state["installed"])
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: state["installed"])

    def fake_install():
        state["installed"] = True
        return True, "설치 완료"

    monkeypatch.setattr(ollama_setup, "install", fake_install)
    monkeypatch.setattr(ollama_setup, "try_start_daemon", lambda: None)
    monkeypatch.setattr(ollama_setup, "wait_for_daemon", lambda *a, **k: True)

    ok, msg = ollama_setup.ensure_ready(auto=True, ask=False)
    assert ok and "설치 완료" in msg


def test_giga_setup_이미_준비됨(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: True)
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: True)
    result = runner.invoke(app, ["setup", "--skip-model"])
    assert result.exit_code == 0
    assert "설치·실행 확인" in result.stdout


def test_giga_setup_비대화_미설치(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: False)
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: False)
    # CliRunner = 비 TTY → 설치 프롬프트 없이 종료
    result = runner.invoke(app, ["setup", "--skip-model"])
    assert result.exit_code == 1


def test_model_use_ollama_없으면_비대화_경고(tmp_path, monkeypatch) -> None:
    import gigachanie.config as cfgmod

    monkeypatch.setattr(cfgmod, "_USER_CONFIG", tmp_path / "config.yaml")
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: False)
    result = runner.invoke(app, ["model", "use", "qwen2.5-coder-7b-instruct"])
    # 설정은 저장되고, ollama 없음 경고 후 정상 종료
    assert result.exit_code == 0
    assert "Ollama 미설치" in result.stdout or "ollama" in result.stdout.lower()

"""Ollama 자동 설치 흐름 테스트 (실제 설치는 하지 않음)."""

from types import SimpleNamespace

from typer.testing import CliRunner

from gigachanie.cli import app
from gigachanie.commands import model as model_command
from gigachanie.providers import hardware
from gigachanie.serving import ollama_setup

runner = CliRunner()


def test_ensure_ready_이미_준비됨(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: True)
    monkeypatch.setattr(
        ollama_setup,
        "is_installed",
        lambda: (_ for _ in ()).throw(AssertionError("설치 여부를 다시 확인하면 안 됨")),
    )
    ok, msg = ollama_setup.ensure_ready(auto=False, ask=False)
    assert ok and "준비" in msg


def test_ensure_ready_미설치_비대화_안내만(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup, "is_installed", lambda: False)
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: False)
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


def test_windows_표준_설치_경로에서_실행파일_탐지(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(ollama_setup.shutil, "which", lambda _command: None)
    monkeypatch.setattr(ollama_setup.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert ollama_setup.executable_path() == str(executable)
    assert ollama_setup.is_installed()


def test_try_start_daemon_이미_실행_중이면_중복_실행_안함(monkeypatch) -> None:
    started = []
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: True)
    monkeypatch.setattr(
        ollama_setup.subprocess,
        "Popen",
        lambda *a, **k: started.append((a, k)),
    )

    ollama_setup.try_start_daemon()

    assert not started


def test_try_start_daemon_탐지한_실행경로_사용(monkeypatch) -> None:
    commands = []
    path = r"C:\Users\테스트\AppData\Local\Programs\Ollama\ollama.exe"
    monkeypatch.setattr(ollama_setup, "daemon_up", lambda *a, **k: False)
    monkeypatch.setattr(ollama_setup, "executable_path", lambda: path)
    monkeypatch.setattr(ollama_setup.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        ollama_setup.subprocess,
        "Popen",
        lambda command, **kwargs: commands.append(command),
    )

    ollama_setup.try_start_daemon()

    assert commands == [[path, "serve"]]


def test_winget_업데이트_없음은_설치_성공으로_처리(monkeypatch) -> None:
    monkeypatch.setattr(ollama_setup.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ollama_setup.shutil, "which", lambda command: f"{command}.exe")
    monkeypatch.setattr(ollama_setup, "_run", lambda _command: 0x8A15002B)

    ok, msg = ollama_setup.install()

    assert ok
    assert "이미 설치" in msg
    assert "실패" not in msg


def test_model_명령도_탐지한_실행경로_사용(monkeypatch) -> None:
    commands = []
    path = r"C:\Users\테스트\AppData\Local\Programs\Ollama\ollama.exe"
    monkeypatch.setattr(ollama_setup, "executable_path", lambda: path)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="NAME\nqwen2.5-coder:7b latest")

    monkeypatch.setattr(model_command.subprocess, "run", fake_run)

    assert model_command._ollama_has("qwen2.5-coder:7b")
    assert model_command._ollama_pull("qwen2.5-coder:7b") == 0
    assert commands == [
        [path, "list"],
        [path, "pull", "qwen2.5-coder:7b"],
    ]


def test_hardware_진단도_탐지한_실행경로_사용(monkeypatch) -> None:
    commands = []
    path = r"C:\Users\테스트\AppData\Local\Programs\Ollama\ollama.exe"
    monkeypatch.setattr(ollama_setup, "executable_path", lambda: path)

    def fake_run(command):
        commands.append(command)
        return "NAME ID SIZE\nqwen2.5-coder:7b latest 4.7GB"

    monkeypatch.setattr(hardware, "_run", fake_run)

    backend = hardware._ollama_backend()

    assert backend.available
    assert backend.detail == "설치됨, 모델 1개"
    assert commands == [[path, "list"]]

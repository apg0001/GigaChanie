"""Ollama 자동 설치 / 데몬 확인.

플랫폼별 설치 명령:
  Windows : winget install --id Ollama.Ollama
  macOS   : brew install --cask ollama  (brew 없으면 수동 안내)
  Linux   : curl -fsSL https://ollama.com/install.sh | sh
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import httpx

_DOWNLOAD_URL = "https://ollama.com/download"
_DEFAULT_HOST = "http://127.0.0.1:11434"
_WINGET_NO_APPLICABLE_UPGRADE = 0x8A15002B


def _windows_executable_candidates() -> tuple[Path, ...]:
    """Windows 설치 프로그램이 사용하는 Ollama 실행 파일 후보를 돌려준다."""
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")
    else:
        candidates.append(Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe")

    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        program_files = os.environ.get(variable)
        if program_files:
            candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
    return tuple(candidates)


def executable_path() -> str | None:
    """PATH와 플랫폼 표준 설치 위치에서 Ollama 실행 파일을 찾는다."""
    path = shutil.which("ollama")
    if path:
        return path
    if platform.system() != "Windows":
        return None
    for candidate in _windows_executable_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def is_installed() -> bool:
    return executable_path() is not None


def daemon_up(host: str = _DEFAULT_HOST) -> bool:
    try:
        r = httpx.get(f"{host}/api/tags", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def wait_for_daemon(timeout: float = 20.0, host: str = _DEFAULT_HOST) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_up(host):
            return True
        time.sleep(1.0)
    return False


def _run(cmd: list[str] | str, *, shell: bool = False) -> int:
    try:
        return subprocess.run(cmd, shell=shell, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def install() -> tuple[bool, str]:
    """플랫폼에 맞는 방법으로 Ollama 를 설치한다. (성공 여부, 메시지)."""
    system = platform.system()

    if system == "Windows":
        if not shutil.which("winget"):
            return False, f"winget 이 없습니다. 수동 설치: {_DOWNLOAD_URL}"
        code = _run(
            [
                "winget",
                "install",
                "--id",
                "Ollama.Ollama",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        )
        if code & 0xFFFFFFFF == _WINGET_NO_APPLICABLE_UPGRADE:
            return True, "Ollama가 이미 설치되어 있으며 최신 버전입니다."
        if code != 0:
            return False, f"winget 설치 실패(코드 {code}). 수동 설치: {_DOWNLOAD_URL}"
        return True, "설치 완료. 새 터미널이 필요할 수 있습니다 (PATH 갱신)."

    if system == "Darwin":
        if shutil.which("brew"):
            code = _run(["brew", "install", "--cask", "ollama"])
            if code == 0:
                return True, "설치 완료. `open -a Ollama` 로 앱을 실행하세요."
            return False, f"brew 설치 실패(코드 {code}). 수동 설치: {_DOWNLOAD_URL}"
        return False, f"Homebrew 가 없습니다. 수동 설치: {_DOWNLOAD_URL}"

    if system == "Linux":
        if not shutil.which("curl"):
            return False, f"curl 이 없습니다. 수동 설치: {_DOWNLOAD_URL}"
        code = _run("curl -fsSL https://ollama.com/install.sh | sh", shell=True)
        if code != 0:
            return False, f"설치 스크립트 실패(코드 {code}). 수동: {_DOWNLOAD_URL}"
        return True, "설치 완료."

    return False, f"지원하지 않는 플랫폼: {system}. 수동 설치: {_DOWNLOAD_URL}"


def try_start_daemon() -> None:
    """데몬을 띄워 본다 (백그라운드). 실패해도 조용히 넘어간다."""
    if daemon_up():
        return
    path = executable_path()
    if path is None:
        return
    try:
        kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            kwargs["creationflags"] = flags
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([path, "serve"], **kwargs)  # type: ignore[call-overload]
    except (OSError, subprocess.SubprocessError):
        return


def ensure_ready(*, auto: bool, ask: bool) -> tuple[bool, str]:
    """Ollama 가 설치·실행 상태가 되도록 시도한다.

    auto=True 면 설치를 바로 진행, ask=True 면 호출부가 확인을 받은 상태.
    반환: (준비됨, 안내 메시지)
    """
    if daemon_up():
        return True, "ollama 준비됨"

    if is_installed():
        try_start_daemon()
        if wait_for_daemon(15):
            return True, "ollama 데몬 시작됨"
        return False, (
            "ollama 는 설치돼 있으나 데몬이 응답하지 않습니다. `ollama serve` 를 실행하세요."
        )

    if not (auto or ask):
        return False, f"ollama 미설치. `giga setup` 또는 수동 설치: {_DOWNLOAD_URL}"

    ok, msg = install()
    if not ok:
        return False, msg
    # 설치 직후 PATH/데몬이 아직 준비 안 됐을 수 있음
    if is_installed():
        try_start_daemon()
    ready = wait_for_daemon(20)
    if ready:
        return True, msg
    return False, msg + " (데몬이 아직 안 떴습니다. 새 터미널에서 다시 시도하세요.)"

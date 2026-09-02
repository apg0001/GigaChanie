"""셸 명령 샌드박싱.

플랫폼별로 가능한 격리 도구를 감지해 `run_shell` / `run_background` 명령을 감싼다.
전부 실패하면 격리 없이 실행하되(승인 정책이 1차 방어), 그 사실을 알린다.

  Linux  : bubblewrap(bwrap) 또는 firejail
  macOS  : sandbox-exec (기본 프로파일)
  Windows: 지원 안 함 (승인 정책·거부 목록에 의존)
"""

from __future__ import annotations

import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxPlan:
    available: bool
    tool: str = ""
    note: str = ""

    def wrap(self, argv: list[str], *, root: Path, allow_net: bool) -> list[str]:
        """샌드박스 실행기로 argv 를 감싼다. available=False 면 그대로 반환."""
        if not self.available:
            return argv
        if self.tool == "bwrap":
            base = [
                "bwrap",
                "--ro-bind", "/", "/",
                "--dev", "/dev",
                "--proc", "/proc",
                "--tmpfs", "/tmp",
                "--bind", str(root), str(root),
                "--chdir", str(root),
                "--die-with-parent",
            ]
            if not allow_net:
                base += ["--unshare-net"]
            return [*base, "--", *argv]
        if self.tool == "firejail":
            base = ["firejail", "--quiet", f"--whitelist={root}", "--private-tmp"]
            if not allow_net:
                base.append("--net=none")
            return [*base, *argv]
        if self.tool == "sandbox-exec":
            profile = _macos_profile(root, allow_net)
            return ["sandbox-exec", "-f", profile, *argv]
        return argv


_MACOS_PROFILE: str | None = None


def _macos_profile(root: Path, allow_net: bool) -> str:
    """쓰기는 작업 루트와 /tmp 로 제한하는 seatbelt 프로파일 파일 경로."""
    global _MACOS_PROFILE
    if _MACOS_PROFILE and Path(_MACOS_PROFILE).is_file():
        return _MACOS_PROFILE
    net = "(allow network*)" if allow_net else "(deny network*)"
    body = f"""(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "{root}"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/private/var/folders"))
{net}
"""
    fd, path = tempfile.mkstemp(prefix="giga-sb-", suffix=".sb")
    os.write(fd, body.encode("utf-8"))
    os.close(fd)
    _MACOS_PROFILE = path
    return path


def detect_sandbox() -> SandboxPlan:
    system = platform.system()
    if system == "Linux":
        if shutil.which("bwrap"):
            return SandboxPlan(available=True, tool="bwrap", note="bubblewrap")
        if shutil.which("firejail"):
            return SandboxPlan(available=True, tool="firejail", note="firejail")
        return SandboxPlan(
            available=False,
            note="bubblewrap/firejail 미설치 (apt install bubblewrap)",
        )
    if system == "Darwin":
        if shutil.which("sandbox-exec"):
            return SandboxPlan(available=True, tool="sandbox-exec", note="seatbelt")
        return SandboxPlan(available=False, note="sandbox-exec 없음")
    return SandboxPlan(
        available=False, note="Windows 는 OS 샌드박스 미지원 - 승인 정책에 의존"
    )

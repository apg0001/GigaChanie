"""자기 점검·업데이트.

GigaChanie 가 자신의 설치 상태를 파악하고(PyPI 최신 버전 확인 포함),
설치 방식에 맞는 방법으로 자신을 업데이트한다. 소스 체크아웃에서 실행 중이면
`giga self fix` 로 에이전트를 자기 저장소에 돌려 문제를 직접 고칠 수 있다.
"""

from __future__ import annotations

import importlib.metadata as _md
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from gigachanie import __version__

_PYPI_URL = "https://pypi.org/pypi/gigachanie/json"


@dataclass(frozen=True)
class InstallInfo:
    version: str
    method: str  # "editable" | "pip" | "pipx" | "unknown"
    location: Path | None  # site-packages 또는 소스 위치
    repo_root: Path | None  # 소스 트리 루트 (pyproject.toml 이 있는 곳)
    has_git: bool

    @property
    def can_self_fix(self) -> bool:
        return self.repo_root is not None


def _dist_location(dist: _md.Distribution) -> Path | None:
    try:
        loc = dist.locate_file("")
    except Exception:
        return None
    return Path(str(loc)).resolve() if loc else None


def _editable_repo(dist: _md.Distribution) -> Path | None:
    try:
        raw = dist.read_text("direct_url.json")
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("dir_info", {}).get("editable"):
        return None
    url = data.get("url", "")
    if not url.startswith("file:"):
        return None
    path = url2pathname(urlparse(url).path)
    p = Path(path)
    return p if p.is_dir() else None


def detect_install() -> InstallInfo:
    method = "unknown"
    location: Path | None = None
    repo_root: Path | None = None

    try:
        dist: _md.Distribution | None = _md.distribution("gigachanie")
    except _md.PackageNotFoundError:
        dist = None

    if dist is not None:
        location = _dist_location(dist)
        repo_root = _editable_repo(dist)
        if repo_root is not None:
            method = "editable"
        elif location is not None and "pipx" in {p.lower() for p in location.parts}:
            method = "pipx"
        else:
            method = "pip"

    if repo_root is None:
        cand = Path(__file__).resolve().parents[2]
        if (cand / "pyproject.toml").is_file():
            repo_root = cand
            if method == "unknown":
                method = "editable"

    has_git = repo_root is not None and (repo_root / ".git").exists()
    return InstallInfo(__version__, method, location, repo_root, has_git)


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def latest_version(*, timeout: float = 5.0) -> str | None:
    """PyPI 에서 최신 배포 버전을 가져온다. 실패 시 None."""
    try:
        import httpx

        resp = httpx.get(_PYPI_URL, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        version = resp.json()["info"]["version"]
        return str(version) if version else None
    except Exception:
        return None


@dataclass(frozen=True)
class UpdateStatus:
    current: str
    latest: str | None
    behind: bool


def check_update(*, timeout: float = 5.0) -> UpdateStatus:
    latest = latest_version(timeout=timeout)
    behind = bool(latest and _vtuple(latest) > _vtuple(__version__))
    return UpdateStatus(__version__, latest, behind)


def update_command(info: InstallInfo) -> list[str]:
    if info.method == "editable":
        if info.has_git and info.repo_root is not None:
            return ["git", "-C", str(info.repo_root), "pull", "--ff-only"]
        return []  # editable 인데 git 이 아니면 자동 업데이트 불가
    if info.method == "pipx":
        return ["pipx", "upgrade", "gigachanie"]
    return [sys.executable, "-m", "pip", "install", "-U", "gigachanie"]


def run_update(info: InstallInfo) -> tuple[bool, str]:
    cmd = update_command(info)
    if not cmd:
        return False, (
            "editable 설치인데 git 저장소가 아니라 자동 업데이트할 수 없습니다. "
            "소스를 직접 갱신하세요."
        )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return False, f"업데이트 명령을 실행할 수 없습니다: {exc}"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def run_diagnostics() -> list[str]:
    """알려진 문제를 훑는다. 반환값이 비어 있으면 이상 없음."""
    issues: list[str] = []

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line and "gigachanie" in line.lower():
                    issues.append(f"의존성: {line}")
    except OSError:
        pass

    try:
        __import__("gigachanie.cli")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"임포트 오류: {exc}")

    return issues


SELF_FIX_PREAMBLE = (
    "너는 지금 GigaChanie(자기 자신)의 소스 저장소에서 실행되고 있다. "
    "아래 문제를 조사해 직접 고쳐라. 필요하면 web_search / web_fetch 로 "
    "최신 문서·이슈를 찾고, 저장소의 코드·테스트를 읽어 원인을 파악한 뒤 "
    "수정하고 `python -m pytest -q` 로 검증해라. "
    "AGENTS.md 의 규칙(문서 동시 갱신 등)을 지켜라.\n\n"
    "문제/요청: "
)

DEFAULT_FIX_TASK = (
    "`python -m pytest -q` 와 `ruff check .`, `mypy src` 를 실행하고, "
    "실패가 있으면 원인을 찾아 고쳐라. 실패가 없으면 그대로 보고만 해라."
)


def self_fix_argv(repo_root: Path, task: str, *, yolo: bool) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "gigachanie",
        "agent",
        "-C",
        str(repo_root),
        "--web",
    ]
    argv.append("--yolo" if yolo else "--write")
    argv.append(SELF_FIX_PREAMBLE + task)
    return argv

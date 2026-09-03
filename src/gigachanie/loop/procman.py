"""백그라운드 프로세스 관리.

dev 서버·빌드 워치처럼 오래 도는 프로세스를 분리 실행하고, 로그를 파일로 받아
tail/wait_for 로 관찰한다. 프로세스 메타데이터는 `.agent/logs/procs.json` 에 기록해
`giga ps` / `giga kill` 이 다른 실행에서도 볼 수 있게 한다.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

WrapFn = Callable[[list[str]], list[str]]

_LOGDIR = Path(".agent") / "logs"
_REGISTRY = "procs.json"
_TAIL_MAX = 8000


@dataclass
class ProcHandle:
    id: str
    pid: int
    cmd: str
    cwd: str
    log: str
    started: str

    def alive(self) -> bool:
        try:
            return psutil.pid_exists(self.pid) and psutil.Process(self.pid).is_running()
        except (psutil.Error, ValueError):
            return False


def _shell_argv(cmd: str) -> list[str]:
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    return ["/bin/sh", "-c", cmd]


class ProcessManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._logdir = (self.root / _LOGDIR).resolve()
        self._popen: dict[str, subprocess.Popen[bytes]] = {}

    # ------------------------------------------------------------- registry

    def _registry_path(self) -> Path:
        return self._logdir / _REGISTRY

    def _load(self) -> list[ProcHandle]:
        p = self._registry_path()
        if not p.is_file():
            return []
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [ProcHandle(**h) for h in data]

    def _save(self, handles: list[ProcHandle]) -> None:
        self._logdir.mkdir(parents=True, exist_ok=True)
        self._registry_path().write_text(
            json.dumps([asdict(h) for h in handles], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    def _prune(self) -> list[ProcHandle]:
        handles = [h for h in self._load() if h.alive()]
        self._save(handles)
        return handles

    # ------------------------------------------------------------- 시작/조회

    def start(
        self, cmd: str, *, cwd: str = ".", wrap: WrapFn | None = None
    ) -> ProcHandle:
        self._logdir.mkdir(parents=True, exist_ok=True)
        pid_seed = f"{cmd}{time.time()}"
        proc_id = re.sub(r"\W", "", cmd.split()[0])[:8].lower() or "proc"
        proc_id = f"{proc_id}-{abs(hash(pid_seed)) % 10000:04d}"
        log_path = self._logdir / f"proc-{proc_id}.log"

        workdir = (self.root / cwd).resolve()
        logf = log_path.open("wb")
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        )
        argv = _shell_argv(cmd)
        if wrap is not None:
            argv = wrap(argv)
        popen = subprocess.Popen(
            argv,
            cwd=str(workdir),
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
            creationflags=creationflags,
        )
        handle = ProcHandle(
            id=proc_id,
            pid=popen.pid,
            cmd=cmd,
            cwd=cwd,
            log=str(log_path),
            started=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._popen[proc_id] = popen
        handles = [h for h in self._load() if h.id != proc_id]
        handles.append(handle)
        self._save(handles)
        return handle

    def list(self) -> list[ProcHandle]:
        return self._prune()

    def get(self, proc_id: str) -> ProcHandle | None:
        for h in self._load():
            if h.id == proc_id:
                return h
        return None

    # ------------------------------------------------------------- 로그/종료

    def tail(self, proc_id: str, lines: int = 40) -> str:
        h = self.get(proc_id)
        if h is None:
            return f"(프로세스 {proc_id} 없음)"
        log = Path(h.log)
        if not log.is_file():
            return "(로그 없음)"
        text = log.read_text("utf-8", errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return tail[-_TAIL_MAX:]

    def wait_for(self, proc_id: str, pattern: str, timeout: float = 30.0) -> tuple[bool, str]:
        h = self.get(proc_id)
        if h is None:
            return False, f"프로세스 {proc_id} 없음"
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return False, f"잘못된 정규식: {exc}"
        log = Path(h.log)
        deadline = time.monotonic() + max(1.0, min(timeout, 300.0))
        while time.monotonic() < deadline:
            if log.is_file():
                content = log.read_text("utf-8", errors="replace")
                if rx.search(content):
                    return True, "패턴 발견"
            if not h.alive():
                return False, "프로세스가 종료됨"
            time.sleep(0.4)
        return False, "시간 초과"

    def stop(self, proc_id: str) -> bool:
        h = self.get(proc_id)
        if h is None:
            return False
        popen = self._popen.get(proc_id)
        try:
            if popen is not None:
                popen.terminate()
                try:
                    popen.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    popen.kill()
            elif h.alive():
                _kill_pid(h.pid)
        except (OSError, psutil.Error):
            pass
        self._popen.pop(proc_id, None)
        self._save([x for x in self._load() if x.id != proc_id])
        return True

    def stop_all(self) -> None:
        for h in list(self._load()):
            self.stop(h.id)


def _kill_pid(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            child.terminate()
        proc.terminate()
        _, alive = psutil.wait_procs([proc], timeout=5)
        for p in alive:
            p.kill()
    except psutil.NoSuchProcess:
        return
    except psutil.Error:
        if os.name != "nt":
            sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
            with contextlib.suppress(OSError):
                os.kill(pid, sigkill)

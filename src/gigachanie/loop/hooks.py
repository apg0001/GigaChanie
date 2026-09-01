"""훅: 이벤트 발생 시 셸 명령 실행.

설정: `<root>/.agent/hooks.yaml`
    session_start:
      - run: "echo start"
    pre_tool:
      - match: "run_shell|write_file"     # 도구 이름 정규식 (없으면 전체)
        run: "./scripts/guard.sh"          # 종료코드 != 0 이면 그 도구 실행 차단
    post_tool:
      - run: "echo done"
    stop:
      - run: "notify-send 'agent 종료'"

훅에는 env 로 GIGA_EVENT, GIGA_TOOL_NAME, GIGA_TOOL_ARGS(JSON), GIGA_ROOT 가 전달되고
stdin 으로도 같은 JSON 이 들어간다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_FILE = Path(".agent") / "hooks.yaml"
_EVENTS = ("session_start", "pre_tool", "post_tool", "stop")
_TIMEOUT = 20


@dataclass(frozen=True)
class Hook:
    run: str
    match: str = ""

    def matches(self, tool_name: str) -> bool:
        if not self.match:
            return True
        try:
            return re.search(self.match, tool_name) is not None
        except re.error:
            return False


@dataclass
class HookRunner:
    root: Path
    hooks: dict[str, list[Hook]] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> HookRunner:
        root = root.resolve()
        path = root / _FILE
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text("utf-8")) or {}
            except (OSError, yaml.YAMLError):
                data = {}
        hooks: dict[str, list[Hook]] = {}
        for ev in _EVENTS:
            entries = data.get(ev) or []
            hooks[ev] = [
                Hook(run=str(e["run"]), match=str(e.get("match", "")))
                for e in entries
                if isinstance(e, dict) and e.get("run")
            ]
        return cls(root=root, hooks=hooks)

    @property
    def enabled(self) -> bool:
        return any(self.hooks.values())

    def _exec(self, hook: Hook, payload: dict[str, Any]) -> tuple[int, str]:
        env = {
            **os.environ,
            "GIGA_EVENT": payload.get("event", ""),
            "GIGA_TOOL_NAME": payload.get("tool", ""),
            "GIGA_TOOL_ARGS": json.dumps(payload.get("args", {}), ensure_ascii=False),
            "GIGA_ROOT": str(self.root),
        }
        try:
            proc = subprocess.run(
                hook.run,
                shell=True,
                cwd=str(self.root),
                env=env,
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, f"훅 실행 실패: {exc}"
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    def fire(self, event: str, *, tool: str = "", args: dict[str, Any] | None = None) -> None:
        """session_start / post_tool / stop 용. 결과는 무시(로그만)."""
        for hook in self.hooks.get(event, []):
            if event == "post_tool" and not hook.matches(tool):
                continue
            self._exec(hook, {"event": event, "tool": tool, "args": args or {}})

    def check_pre_tool(self, tool: str, args: dict[str, Any]) -> str | None:
        """pre_tool 훅을 실행한다. 하나라도 종료코드 != 0 이면 차단 사유(str) 반환."""
        for hook in self.hooks.get("pre_tool", []):
            if not hook.matches(tool):
                continue
            code, out = self._exec(hook, {"event": "pre_tool", "tool": tool, "args": args})
            if code != 0:
                return f"pre_tool 훅이 차단함 (코드 {code}): {out or hook.run}"
        return None

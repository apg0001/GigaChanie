"""실행 로그 (JSONL).

에이전트 run 한 건당 한 줄을 `<root>/.agent/logs/runs.jsonl` 에 append 한다.
프롬프트/모델/도구를 바꿔가며 통과율·스텝·토큰 추이를 보는 용도.
`jq` 나 `giga eval` 리포트와 함께 쓴다.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from gigachanie.loop.agent import AgentEvent, AgentResult

_FILE = Path(".agent") / "logs" / "runs.jsonl"


def git_changed_files(root: Path) -> list[str]:
    """작업 루트에서 HEAD 대비 변경된 파일 목록 (git 없으면 빈 목록)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout
    except OSError:
        return []
    return out.split()


class RunLogger:
    """이벤트를 모아 run 종료 시 한 줄로 기록한다."""

    def __init__(self, root: Path, *, task: str, model: str) -> None:
        self._path = (root.resolve() / _FILE).resolve()
        self._task = task
        self._model = model
        self._started = time.time()
        self._tools: Counter[str] = Counter()
        self._edit_failures = 0

    def observe(self, ev: AgentEvent) -> None:
        if ev.kind == "tool_call":
            self._tools[ev.tool_name] += 1
        elif ev.kind == "tool_result" and ev.is_error and (
            "편집 실패" in ev.text or "편집 거부" in ev.text
        ):
            self._edit_failures += 1

    def finish(self, result: AgentResult, *, changed_files: list[str] | None = None) -> None:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "task": self._task[:200],
            "model": self._model,
            "ok": result.ok,
            "stop_reason": result.stop_reason,
            "steps": result.steps,
            "tokens": {
                "prompt": result.usage.prompt_tokens,
                "completion": result.usage.completion_tokens,
                "total": result.usage.total_tokens,
            },
            "tools": dict(self._tools),
            "edit_failures": self._edit_failures,
            "changed_files": changed_files or [],
            "seconds": round(time.time() - self._started, 1),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

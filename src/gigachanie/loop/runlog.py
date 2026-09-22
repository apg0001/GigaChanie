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

from gigachanie.loop.agent import Agent, AgentEvent, AgentResult

_FILE = Path(".agent") / "logs" / "runs.jsonl"


def _git_lines(root: Path, args: list[str]) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout
    except OSError:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def git_changed_files(root: Path) -> list[str]:
    """작업 루트에서 HEAD 대비 변경된 파일 목록 (git 없으면 빈 목록).

    추적 중인 파일의 수정분(`git diff --name-only HEAD`)과 새로 만들어
    아직 커밋되지 않은(untracked, gitignore 제외) 파일을 모두 포함한다.
    전자만 보면 에이전트가 write_file 로 만든 새 파일이 하나도 안 잡힌다.
    """
    tracked = _git_lines(root, ["diff", "--name-only", "HEAD"])
    untracked = _git_lines(root, ["ls-files", "--others", "--exclude-standard"])
    seen: set[str] = set()
    out: list[str] = []
    for f in (*tracked, *untracked):
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def resolve_changed_files(agent: Agent, root: Path) -> list[str]:
    """방금 turn 에서 실제로 바뀐 파일 목록.

    체크포인트가 켜져 있으면 그 턴 단위 기록(`Agent.last_changed_files`)을 쓴다 —
    git diff 는 HEAD 기준 누적이라, 커밋 없이 여러 턴을 거치면 이전 턴에서
    바뀐 파일까지 계속 섞여 나온다. 체크포인트가 꺼져 있으면(읽기전용,
    `--no-checkpoint`) 그 정밀도를 포기하고 git diff 로 대체한다.
    """
    if agent.last_changed_files is not None:
        return agent.last_changed_files
    return git_changed_files(root)


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

        from gigachanie.loop.otel import emit_run_span

        emit_run_span(
            name="giga.agent.run",
            started=self._started,
            attributes={
                "model": self._model,
                "ok": bool(result.ok),
                "stop_reason": result.stop_reason,
                "steps": result.steps,
                "tokens.total": result.usage.total_tokens,
                "edit_failures": self._edit_failures,
                "changed_files": len(changed_files or []),
            },
        )

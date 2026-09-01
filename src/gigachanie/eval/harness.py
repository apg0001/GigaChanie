"""평가 하네스.

태스크 = 초기 파일 트리 + 지시문 + 판정. 각 태스크를 임시 디렉터리에 복제하고
에이전트를 (쓰기 도구 활성, full-auto) 실행한 뒤 판정을 돌려 통과 여부를 본다.

태스크 디렉터리 구조:
    tasks/<name>/
      task.yaml       # prompt, max_steps, check
      repo/           # 초기 파일 트리 (에이전트 작업 루트로 복제됨)

task.yaml:
    prompt: "설명 ..."
    max_steps: 15
    check:
      - { type: file_contains, path: "src/x.py", text: "return a + b" }
      - { type: file_absent, path: "TODO" }
      - { type: shell, cmd: "python -m pytest -q", cwd: "." }   # 종료코드 0 = 통과
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from gigachanie.loop.agent import Agent, AgentResult
from gigachanie.loop.approval import ApprovalMode, ApprovalPolicy
from gigachanie.loop.builtin_tools import build_registry
from gigachanie.loop.tools import ToolContext
from gigachanie.serving.base import Backend

AgentFactory = Callable[[Backend, ToolContext, int], Agent]


@dataclass(frozen=True)
class Check:
    type: str
    path: str = ""
    text: str = ""
    cmd: str = ""
    cwd: str = "."


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    checks: tuple[Check, ...]
    max_steps: int = 15
    repo_dir: Path | None = None


@dataclass
class CheckResult:
    check: Check
    passed: bool
    detail: str = ""


@dataclass
class TaskResult:
    task: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    steps: int = 0
    total_tokens: int = 0
    edit_failures: int = 0
    stop_reason: str = ""
    seconds: float = 0.0
    error: str = ""


@dataclass
class EvalReport:
    results: list[TaskResult] = field(default_factory=list)
    model: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.results else 0.0

    @property
    def total_edit_failures(self) -> int:
        return sum(r.edit_failures for r in self.results)


# --------------------------------------------------------------- 태스크 로딩


def load_tasks(tasks_dir: Path, names: list[str] | None = None) -> list[Task]:
    tasks: list[Task] = []
    for d in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
        if names and d.name not in names:
            continue
        spec_file = d / "task.yaml"
        if not spec_file.is_file():
            continue
        spec = yaml.safe_load(spec_file.read_text("utf-8")) or {}
        checks = tuple(
            Check(
                type=c["type"],
                path=c.get("path", ""),
                text=c.get("text", ""),
                cmd=c.get("cmd", ""),
                cwd=c.get("cwd", "."),
            )
            for c in spec.get("check", [])
        )
        repo = d / "repo"
        tasks.append(
            Task(
                name=d.name,
                prompt=spec["prompt"],
                checks=checks,
                max_steps=int(spec.get("max_steps", 15)),
                repo_dir=repo if repo.is_dir() else None,
            )
        )
    return tasks


# --------------------------------------------------------------- 판정


def _run_check(check: Check, root: Path) -> CheckResult:
    if check.type == "file_contains":
        p = root / check.path
        if not p.is_file():
            return CheckResult(check, False, f"파일 없음: {check.path}")
        ok = check.text in p.read_text("utf-8", errors="replace")
        return CheckResult(check, ok, "" if ok else f"'{check.text}' 미포함")
    if check.type == "file_absent":
        exists = (root / check.path).exists()
        return CheckResult(check, not exists, "" if not exists else "파일이 존재함")
    if check.type == "file_present":
        exists = (root / check.path).exists()
        return CheckResult(check, exists, "" if exists else "파일 없음")
    if check.type == "shell":
        try:
            proc = subprocess.run(
                check.cmd,
                shell=True,
                cwd=str(root / check.cwd),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult(check, False, f"실행 실패: {exc}")
        ok = proc.returncode == 0
        tail = (proc.stdout + proc.stderr)[-300:]
        return CheckResult(check, ok, "" if ok else f"exit {proc.returncode}: {tail}")
    return CheckResult(check, False, f"알 수 없는 판정 유형: {check.type}")


# --------------------------------------------------------------- 실행


def _default_agent_factory(backend: Backend, ctx: ToolContext, max_steps: int) -> Agent:
    return Agent(
        backend,
        build_registry(writable=True),
        ctx,
        max_steps=max_steps,
        temperature=0.0,
    )


async def run_task(
    task: Task,
    backend: Backend,
    *,
    agent_factory: AgentFactory | None = None,
    run_agent: Callable[[Agent, str], Awaitable[AgentResult]] | None = None,
) -> TaskResult:
    factory = agent_factory or _default_agent_factory
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix=f"giga-eval-{task.name}-"))
    try:
        if task.repo_dir is not None:
            shutil.copytree(task.repo_dir, workdir, dirs_exist_ok=True)

        ctx = ToolContext(
            root=workdir,
            policy=ApprovalPolicy(mode=ApprovalMode.FULL_AUTO, approver=None),
        )
        agent = factory(backend, ctx, task.max_steps)

        edit_failures = {"n": 0}

        def _count(ev: object) -> None:
            kind = getattr(ev, "kind", "")
            text = getattr(ev, "text", "")
            if kind == "tool_result" and getattr(ev, "is_error", False) and (
                "편집 실패" in text or "편집 거부" in text
            ):
                edit_failures["n"] += 1

        if run_agent is not None:
            result = await run_agent(agent, task.prompt)
        else:
            result = await agent.run(task.prompt, on_event=_count)

        check_results = [_run_check(c, workdir) for c in task.checks]
        passed = bool(check_results) and all(cr.passed for cr in check_results)

        return TaskResult(
            task=task.name,
            passed=passed,
            checks=check_results,
            steps=result.steps,
            total_tokens=result.usage.total_tokens,
            edit_failures=edit_failures["n"],
            stop_reason=result.stop_reason,
            seconds=round(time.monotonic() - started, 1),
        )
    except Exception as exc:  # 태스크 하나가 죽어도 나머지는 계속
        return TaskResult(
            task=task.name,
            passed=False,
            steps=0,
            seconds=round(time.monotonic() - started, 1),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

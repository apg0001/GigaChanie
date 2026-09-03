"""백그라운드 프로세스 도구.

run_background, tail_logs, wait_for_log, stop_process, list_processes.
"""

from __future__ import annotations

from typing import Any

from gigachanie.loop.approval import ApprovalRequest
from gigachanie.loop.procman import ProcessManager
from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult


def _pm(ctx: ToolContext) -> ProcessManager:
    if ctx.procman is None:
        raise ToolError("백그라운드 프로세스 기능이 비활성 상태입니다.")
    return ctx.procman


async def _run_background(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    cmd = args.get("command") or args.get("cmd")
    if not cmd or not isinstance(cmd, str):
        raise ToolError("command 인자(문자열)가 필요합니다.")
    cwd = str(args.get("cwd", "."))

    allowed, reason = ctx.policy.check(
        ApprovalRequest(kind="shell", summary=f"백그라운드 실행: {cmd}", detail=cmd)
    )
    if not allowed:
        return ToolResult.error(f"실행 거부됨 ({reason}): {cmd}")

    wrap = None
    sb = ctx.sandbox
    if sb is not None and getattr(sb, "available", False):
        wrap = lambda argv: sb.wrap(  # noqa: E731
            argv, root=ctx.root, allow_net=ctx.allow_network
        )
    h = _pm(ctx).start(cmd, cwd=cwd, wrap=wrap)
    tag = f" [{sb.tool}]" if wrap is not None else ""
    return ToolResult(
        content=(
            f"시작됨: id={h.id} pid={h.pid}{tag}\n{cmd}\n"
            f"로그 확인은 tail_logs(id=\"{h.id}\"), 종료는 stop_process(id=\"{h.id}\")"
        )
    )


async def _tail_logs(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    proc_id = args.get("id")
    if not proc_id:
        raise ToolError("id 인자가 필요합니다.")
    lines = int(args.get("lines", 40) or 40)
    return ToolResult(content=_pm(ctx).tail(str(proc_id), lines=max(1, min(lines, 500))))


async def _wait_for_log(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    proc_id = args.get("id")
    pattern = args.get("pattern")
    if not proc_id or not pattern:
        raise ToolError("id 와 pattern 인자가 필요합니다.")
    timeout = float(args.get("timeout", 30) or 30)
    ok, msg = _pm(ctx).wait_for(str(proc_id), str(pattern), timeout=timeout)
    tail = _pm(ctx).tail(str(proc_id), lines=20)
    status = "OK" if ok else "실패"
    return ToolResult(content=f"[{status}] {msg}\n--- 최근 로그 ---\n{tail}", is_error=not ok)


async def _stop_process(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    proc_id = args.get("id")
    if not proc_id:
        raise ToolError("id 인자가 필요합니다.")
    ok = _pm(ctx).stop(str(proc_id))
    msg = f"종료됨: {proc_id}" if ok else f"프로세스 {proc_id} 없음"
    return ToolResult(content=msg, is_error=not ok)


async def _list_processes(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    procs = _pm(ctx).list()
    if not procs:
        return ToolResult(content="실행 중인 백그라운드 프로세스 없음")
    rows = [f"{p.id}  pid={p.pid}  ({p.started})  {p.cmd}" for p in procs]
    return ToolResult(content="\n".join(rows))


def register_proc_tools(reg: ToolRegistry) -> None:
    reg.register_func(
        "run_background",
        "오래 도는 명령(dev 서버, 빌드 워치 등)을 백그라운드로 실행하고 즉시 핸들을 돌려준다. "
        "일반 명령은 run_shell 을 쓴다.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "작업 루트 기준 상대경로. 기본 '.'"},
            },
            "required": ["command"],
        },
        _run_background,
    )
    reg.register_func(
        "tail_logs",
        "백그라운드 프로세스의 최근 로그를 본다.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "lines": {"type": "integer", "description": "마지막 N줄. 기본 40"},
            },
            "required": ["id"],
        },
        _tail_logs,
    )
    reg.register_func(
        "wait_for_log",
        "백그라운드 프로세스 로그에 정규식 패턴이 나타날 때까지 기다린다(예: 'Listening on').",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "pattern": {"type": "string"},
                "timeout": {"type": "number", "description": "초. 기본 30, 최대 300"},
            },
            "required": ["id", "pattern"],
        },
        _wait_for_log,
    )
    reg.register_func(
        "stop_process",
        "백그라운드 프로세스를 종료한다.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        _stop_process,
    )
    reg.register_func(
        "list_processes",
        "실행 중인 백그라운드 프로세스 목록.",
        {"type": "object", "properties": {}},
        _list_processes,
    )

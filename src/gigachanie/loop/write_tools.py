"""쓰기/실행 도구: write_file, run_shell.

실행 전 `ctx.policy.check()` 로 승인을 받는다. 거부되면 그 사유를 도구 결과로
모델에 돌려준다(루프는 계속된다).
"""

from __future__ import annotations

import asyncio
import difflib
import os
from typing import Any

from gigachanie.loop.approval import ApprovalRequest
from gigachanie.loop.edit import EditError, apply_edit
from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult

_MAX_OUTPUT = 20_000
_DEFAULT_TIMEOUT = 60


def _unified_diff(old: str, new: str, path: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    text = "".join(diff)
    return text or "(내용 동일)"


async def _write_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = args.get("path")
    if not path:
        raise ToolError("path 인자가 필요합니다.")
    if "content" not in args:
        raise ToolError("content 인자가 필요합니다.")
    new_content = args["content"]
    if not isinstance(new_content, str):
        raise ToolError("content 는 문자열이어야 합니다.")

    target = ctx.resolve(path)
    exists = target.is_file()
    old_content = target.read_text("utf-8", errors="replace") if exists else ""

    if exists and old_content == new_content:
        return ToolResult(content=f"변경 없음: {path}")

    diff = _unified_diff(old_content, new_content, path)
    verb = "덮어쓰기" if exists else "새 파일"
    allowed, reason = ctx.policy.check(
        ApprovalRequest(kind="write", summary=f"{verb}: {path}", detail=diff, path=str(path))
    )
    if not allowed:
        return ToolResult.error(f"쓰기 거부됨 ({reason}): {path}")

    ctx.snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    added = new_content.count("\n") + 1
    removed = old_content.count("\n") + 1 if exists else 0
    return ToolResult(
        content=f"{'수정' if exists else '생성'}됨: {path} (+{added}/-{removed} 행)\n{diff[:2000]}"
    )


async def _apply_edit(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = args.get("path")
    if not path:
        raise ToolError("path 인자가 필요합니다.")
    if "search" not in args or "replace" not in args:
        raise ToolError("search 와 replace 인자가 필요합니다.")
    search, replace = args["search"], args["replace"]
    if not isinstance(search, str) or not isinstance(replace, str):
        raise ToolError("search / replace 는 문자열이어야 합니다.")

    target = ctx.resolve(path)
    exists = target.is_file()
    old = target.read_text("utf-8", errors="replace") if exists else ""

    try:
        result = apply_edit(old, search, replace, file_exists=exists)
    except EditError as exc:
        return ToolResult.error(f"편집 실패 ({path}): {exc}")

    if result.new_content == old:
        return ToolResult(content=f"변경 없음: {path}")

    diff = _unified_diff(old, result.new_content, path)
    allowed, reason = ctx.policy.check(
        ApprovalRequest(
            kind="write",
            summary=f"편집: {path} ({result.method.value})",
            detail=diff,
            path=str(path),
        )
    )
    if not allowed:
        return ToolResult.error(f"편집 거부됨 ({reason}): {path}")

    ctx.snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.new_content, encoding="utf-8")
    where = f" @{result.start_line}행" if result.start_line else ""
    return ToolResult(
        content=f"편집 적용됨: {path}{where} (매칭: {result.method.value})\n{diff[:2000]}"
    )


def _shell_argv(cmd: str) -> list[str]:
    if os.name == "nt":
        # PowerShell 은 네이티브 명령의 종료코드를 자기 종료코드로 전파하지 않으므로
        # 마지막에 명시적으로 exit 를 붙인다.
        wrapped = f"{cmd}\nif ($LASTEXITCODE -ne $null) {{ exit $LASTEXITCODE }}"
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped]
    return ["/bin/sh", "-c", cmd]


async def _run_shell(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    cmd = args.get("command") or args.get("cmd")
    if not cmd or not isinstance(cmd, str):
        raise ToolError("command 인자(문자열)가 필요합니다.")
    timeout = int(args.get("timeout", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT)
    timeout = max(1, min(timeout, 600))

    allowed, reason = ctx.policy.check(
        ApprovalRequest(kind="shell", summary=f"셸 실행: {cmd}", detail=cmd)
    )
    if not allowed:
        return ToolResult.error(f"명령 거부됨 ({reason}): {cmd}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *_shell_argv(cmd),
            cwd=str(ctx.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        raise ToolError(f"명령을 시작할 수 없습니다: {exc}") from exc

    try:
        out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult.error(f"시간 초과({timeout}s): {cmd}")

    output = out_bytes.decode("utf-8", errors="replace")
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + f"\n... [{_MAX_OUTPUT}자에서 잘림]"
    code = proc.returncode
    header = f"$ {cmd}\n[종료코드 {code}]"
    body = output.strip() or "(출력 없음)"
    return ToolResult(content=f"{header}\n{body}", is_error=bool(code))


def register_write_tools(reg: ToolRegistry) -> None:
    reg.register_func(
        "apply_edit",
        "파일의 일부를 바꾼다. search(현재 코드 그대로) 를 찾아 replace 로 교체한다. "
        "search 는 파일에서 유일하게 식별되도록 충분한 문맥을 포함해야 한다. "
        "새 파일을 만들려면 search 를 빈 문자열로 두고 replace 에 전체 내용을 넣는다.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "search": {"type": "string", "description": "교체할 기존 텍스트(정확히)"},
                "replace": {"type": "string", "description": "새 텍스트"},
            },
            "required": ["path", "search", "replace"],
        },
        _apply_edit,
    )
    reg.register_func(
        "write_file",
        "파일 전체 내용을 쓴다(신규 생성 또는 덮어쓰기). 부분 수정은 apply_edit 를 쓴다.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string", "description": "파일 전체 내용"},
            },
            "required": ["path", "content"],
        },
        _write_file,
    )
    reg.register_func(
        "run_shell",
        "셸 명령을 작업 루트에서 실행한다(Windows=PowerShell, 그 외=sh). "
        "stdout+stderr 와 종료코드를 돌려준다.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "초. 기본 60, 최대 600"},
            },
            "required": ["command"],
        },
        _run_shell,
    )

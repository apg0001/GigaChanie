"""기본 제공 도구 (읽기 전용).

#5 범위: list_dir, read_file, glob, grep. 파일 수정/셸 실행은 이후 이슈에서 추가.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from gigachanie.loop.tools import ToolContext, ToolError, ToolRegistry, ToolResult

_MAX_READ_BYTES = 200_000
_MAX_MATCHES = 200
_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".agent",
}


def _iter_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _IGNORE_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def _rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


async def _list_dir(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    target = ctx.resolve(args.get("path", "."))
    if not target.exists():
        raise ToolError(f"경로가 없습니다: {args.get('path', '.')}")
    if not target.is_dir():
        raise ToolError(f"디렉터리가 아닙니다: {args.get('path', '.')}")
    entries: list[str] = []
    for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        if child.name in _IGNORE_DIRS:
            continue
        mark = "/" if child.is_dir() else ""
        size = f"  ({child.stat().st_size}B)" if child.is_file() else ""
        entries.append(f"{_rel(child, ctx.root)}{mark}{size}")
    body = "\n".join(entries) if entries else "(빈 디렉터리)"
    return ToolResult(content=body)


async def _read_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = args.get("path")
    if not path:
        raise ToolError("path 인자가 필요합니다.")
    target = ctx.resolve(path)
    if not target.is_file():
        raise ToolError(f"파일이 없습니다: {path}")
    data = target.read_bytes()
    truncated = len(data) > _MAX_READ_BYTES
    text = data[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
    lines = text.splitlines()

    start = int(args.get("start_line", 1) or 1)
    end_arg = args.get("end_line")
    end = int(end_arg) if end_arg else len(lines)
    start = max(start, 1)
    end = min(end, len(lines))
    selected = lines[start - 1 : end]

    numbered = "\n".join(f"{i:>6}\t{ln}" for i, ln in enumerate(selected, start=start))
    note = ""
    if ctx.policy.path_denied(str(path).replace("\\", "/")):
        note += "\n[주의: 민감정보일 수 있는 파일입니다. 내용을 요약·출력·전송하지 마세요.]"
    if truncated:
        note += f"\n\n[{_MAX_READ_BYTES} 바이트에서 잘림]"
    if start > 1 or end < len(lines):
        note += f"\n[{start}-{end} 행 / 전체 {len(lines)} 행]"
    return ToolResult(content=(numbered or "(빈 파일)") + note)


async def _glob(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    pattern = args.get("pattern")
    if not pattern:
        raise ToolError("pattern 인자가 필요합니다 (예: '**/*.py').")
    matches: list[str] = []
    for p in _iter_files(ctx.root):
        rel = _rel(p, ctx.root)
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
            matches.append(rel)
            if len(matches) >= _MAX_MATCHES:
                break
    matches.sort()
    body = "\n".join(matches) if matches else "(일치하는 파일 없음)"
    return ToolResult(content=body)


async def _grep(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    pattern = args.get("pattern")
    if not pattern:
        raise ToolError("pattern 인자가 필요합니다.")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"잘못된 정규식: {exc}") from exc

    path_glob = args.get("glob") or "*"
    hits: list[str] = []
    scanned = 0
    for p in _iter_files(ctx.root):
        rel = _rel(p, ctx.root)
        if not (fnmatch.fnmatch(rel, path_glob) or fnmatch.fnmatch(p.name, path_glob)):
            continue
        try:
            content = p.read_text("utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for lineno, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                if len(hits) >= _MAX_MATCHES:
                    break
        if len(hits) >= _MAX_MATCHES:
            hits.append(f"... ({_MAX_MATCHES}건에서 중단)")
            break
    body = "\n".join(hits) if hits else f"(일치 없음, 파일 {scanned}개 검색)"
    return ToolResult(content=body)


_NO_USER_HINT = (
    "지금은 대화형 세션이 아니어서 사용자에게 물을 수 없습니다. "
    "가장 합리적인 가정을 선택해 진행하되, 되돌리기 어려운 작업은 피하고 "
    "최종 답변에서 어떤 가정을 했는지 밝히세요."
)


async def _ask_user(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    question = args.get("question")
    if not question or not isinstance(question, str):
        raise ToolError("question 인자(문자열)가 필요합니다.")
    raw_options = args.get("options") or []
    options = [str(o) for o in raw_options] if isinstance(raw_options, list) else []
    allow_custom = bool(args.get("allow_custom", True))

    if ctx.ask_user is None:
        return ToolResult(content=_NO_USER_HINT)

    answer = ctx.ask_user(question, options, allow_custom)
    if not answer.strip():
        return ToolResult(content="(사용자가 답하지 않았습니다. 합리적으로 가정하고 진행하세요.)")
    return ToolResult(content=f"사용자 답변: {answer.strip()}")


def register_readonly_tools(reg: ToolRegistry) -> None:
    reg.register_func(
        "list_dir",
        "디렉터리의 파일/하위 디렉터리 목록을 본다.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "작업 루트 기준 상대경로. 기본 '.'"}
            },
        },
        _list_dir,
    )
    reg.register_func(
        "read_file",
        "파일 내용을 행 번호와 함께 읽는다.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "시작 행(1부터). 선택."},
                "end_line": {"type": "integer", "description": "끝 행(포함). 선택."},
            },
            "required": ["path"],
        },
        _read_file,
    )
    reg.register_func(
        "glob",
        "glob 패턴으로 파일 경로를 찾는다. 예: '**/*.py', 'src/**/test_*.py'",
        {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
        _glob,
    )
    reg.register_func(
        "grep",
        "정규식으로 파일 내용을 검색한다. glob 으로 대상 파일을 좁힐 수 있다.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "파이썬 정규식"},
                "glob": {"type": "string", "description": "대상 파일 glob. 기본 '*'"},
            },
            "required": ["pattern"],
        },
        _grep,
    )
    reg.register_func(
        "ask_user",
        "사용자만 결정할 수 있는 모호한 지점(방향·우선순위·되돌리기 어려운 선택)에서 "
        "추측 대신 사용자에게 묻는다. options 로 선택지를 주면 사용자가 고르거나 직접 입력한다. "
        "코드/문서로 확인 가능한 것은 먼저 도구로 조사하고, 남발하지 않는다.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "선택지 (선택). 없으면 자유 입력만 받는다.",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": "선택지 외 자유 입력 허용. 기본 true",
                },
            },
            "required": ["question"],
        },
        _ask_user,
    )


def default_readonly_registry() -> ToolRegistry:
    from gigachanie.loop.memory_tools import register_read_memory

    reg = ToolRegistry()
    register_readonly_tools(reg)
    register_read_memory(reg)
    return reg


def build_registry(*, writable: bool = False, web: bool = False) -> ToolRegistry:
    """읽기 도구 + (옵션) 쓰기/실행 도구 + (옵션) 웹 도구를 등록한 레지스트리."""
    reg = default_readonly_registry()
    if writable:
        from gigachanie.loop.memory_tools import register_save_memory
        from gigachanie.loop.proc_tools import register_proc_tools
        from gigachanie.loop.write_tools import register_write_tools

        register_write_tools(reg)
        register_save_memory(reg)
        register_proc_tools(reg)
    if web:
        from gigachanie.loop.web_tools import register_web_tools

        register_web_tools(reg)
    return reg

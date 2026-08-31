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
    if truncated:
        note = f"\n\n[{_MAX_READ_BYTES} 바이트에서 잘림]"
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


def default_readonly_registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_readonly_tools(reg)
    return reg

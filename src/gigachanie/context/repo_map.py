"""저장소 맵.

소스 파일의 심볼을 추출하고, 파일 간 참조 그래프에 PageRank 를 돌려
중요한 파일부터 심볼 개요를 토큰 예산 안에서 텍스트로 만든다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from gigachanie.context.symbols import SOURCE_EXTS, FileSymbols, Symbol, extract_symbols

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build", "target",
    ".next", ".nuxt", "vendor", ".agent", "coverage",
}
_MAX_FILE_BYTES = 200_000
_DAMPING = 0.85
_ITERATIONS = 20


@dataclass
class FileEntry:
    path: str
    fs: FileSymbols
    score: float = 0.0

    @property
    def n_defs(self) -> int:
        return len(self.fs.def_names)


@dataclass
class RepoMap:
    text: str
    entries: list[FileEntry] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.entries)


def _iter_source_files(root: Path, max_files: int) -> list[Path]:
    found: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix not in SOURCE_EXTS:
            continue
        if any(part in _IGNORE_DIRS for part in p.relative_to(root).parts):
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        found.append(p)
        if len(found) >= max_files:
            break
    return found


def _pagerank(n: int, out_edges: list[dict[int, float]]) -> list[float]:
    if n == 0:
        return []
    rank = [1.0 / n] * n
    out_sum = [sum(e.values()) or 1.0 for e in out_edges]
    # 역방향 인덱스: j -> [(i, weight)]
    incoming: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for i, edges in enumerate(out_edges):
        for j, w in edges.items():
            incoming[j].append((i, w))

    base = (1.0 - _DAMPING) / n
    for _ in range(_ITERATIONS):
        new = [base] * n
        for j in range(n):
            s = 0.0
            for i, w in incoming[j]:
                s += rank[i] * w / out_sum[i]
            new[j] += _DAMPING * s
        rank = new
    return rank


def build_repo_map(
    root: Path,
    *,
    cwd: Path | None = None,
    max_files: int = 400,
    budget_chars: int = 8000,
) -> RepoMap:
    root = root.resolve()
    cwd = (cwd or root).resolve()
    files = _iter_source_files(root, max_files)
    if not files:
        return RepoMap(text="")

    entries: list[FileEntry] = []
    for p in files:
        try:
            text = p.read_text("utf-8", errors="replace")
        except OSError:
            continue
        fs = extract_symbols(p.suffix, text)
        if not fs.symbols:
            continue
        entries.append(FileEntry(path=p.relative_to(root).as_posix(), fs=fs))

    if not entries:
        return RepoMap(text="")

    # 심볼 이름 -> 정의한 파일 인덱스들
    defs: dict[str, list[int]] = {}
    for idx, e in enumerate(entries):
        for name in e.fs.def_names:
            defs.setdefault(name, []).append(idx)

    out_edges: list[dict[int, float]] = [{} for _ in entries]
    for i, e in enumerate(entries):
        for ref in e.fs.referenced:
            for j in defs.get(ref, ()):
                if j != i:
                    out_edges[i][j] = out_edges[i].get(j, 0.0) + 1.0

    ranks = _pagerank(len(entries), out_edges)
    for e, r in zip(entries, ranks, strict=True):
        boost = 1.0 + math.log1p(e.n_defs)
        if (root / e.path).resolve().is_relative_to(cwd):
            boost *= 1.15
        e.score = r * boost

    entries.sort(key=lambda x: x.score, reverse=True)
    text = _render(entries, budget_chars)
    return RepoMap(text=text, entries=entries)


def _render(entries: list[FileEntry], budget_chars: int) -> str:
    header = "저장소 맵 (참조 랭킹 상위 파일의 심볼 개요):\n"
    blocks: list[str] = []
    total = len(header)

    for i, e in enumerate(entries):
        block = _render_file(e)
        if total + len(block) > budget_chars and blocks:
            blocks.append(f"… (그 외 {len(entries) - i} 파일 생략)")
            break
        blocks.append(block)
        total += len(block)

    return (header + "\n".join(blocks)).strip()


def _render_file(e: FileEntry, max_symbol_lines: int = 14) -> str:
    rows: list[str] = [e.path]
    classes: dict[str, list[Symbol]] = {}
    top: list[Symbol] = []
    for s in e.fs.symbols:
        if s.kind == "class":
            classes.setdefault(s.name, [])
        elif s.kind == "method":
            classes.setdefault(s.parent, []).append(s)
        else:
            top.append(s)

    count = 0
    for cname, methods in classes.items():
        rows.append(f"  class {cname}")
        count += 1
        for m in methods:
            if count >= max_symbol_lines:
                break
            rows.append(f"    {m.signature}")
            count += 1
    for s in top:
        if count >= max_symbol_lines:
            rows.append("    …")
            break
        prefix = "  " if s.kind == "const" else "  "
        rows.append(f"{prefix}{s.signature}")
        count += 1
    return "\n".join(rows) + "\n"

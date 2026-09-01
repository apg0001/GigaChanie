"""프로젝트 컨텍스트 파일 로더.

AGENTS.md(권장) 를 우선 사용하고, 없으면 GEMINI.md / CLAUDE.md / .agent/context.md 를
인식한다. 계층 병합: 사용자 전역(~/.config/gigachanie/AGENTS.md) → 프로젝트 루트 →
작업 디렉터리로 내려가며 발견되는 모든 파일을 순서대로 합친다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_config_path

CONTEXT_FILENAMES = ("AGENTS.md", "GEMINI.md", "CLAUDE.md")
_NESTED = Path(".agent") / "context.md"
_MAX_TOTAL_CHARS = 12_000


@dataclass
class ProjectContext:
    text: str = ""
    sources: list[Path] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.sources)


def _first_context_file(directory: Path) -> Path | None:
    for name in CONTEXT_FILENAMES:
        p = directory / name
        if p.is_file():
            return p
    nested = directory / _NESTED
    if nested.is_file():
        return nested
    return None


def _global_context_file() -> Path | None:
    base = user_config_path("gigachanie", appauthor=False, ensure_exists=False)
    for name in CONTEXT_FILENAMES:
        p = base / name
        if p.is_file():
            return p
    return None


def _dirs_root_to_cwd(root: Path, cwd: Path) -> list[Path]:
    root = root.resolve()
    cwd = cwd.resolve()
    if root == cwd:
        return [root]
    try:
        rel_parts = cwd.relative_to(root).parts
    except ValueError:
        return [root]
    dirs = [root]
    cur = root
    for part in rel_parts:
        cur = cur / part
        dirs.append(cur)
    return dirs


def load_project_context(
    root: Path, cwd: Path | None = None, *, include_global: bool = True
) -> ProjectContext:
    cwd = cwd or root
    candidates: list[Path] = []

    if include_global:
        g = _global_context_file()
        if g is not None:
            candidates.append(g)

    for d in _dirs_root_to_cwd(root, cwd):
        f = _first_context_file(d)
        if f is not None and f not in candidates:
            candidates.append(f)

    if not candidates:
        return ProjectContext()

    chunks: list[str] = []
    used: list[Path] = []
    total = 0
    for path in candidates:
        try:
            body = path.read_text("utf-8", errors="replace").strip()
        except OSError:
            continue
        if not body:
            continue
        header = f"# 컨텍스트 파일: {path.name}"
        piece = f"{header}\n{body}"
        if total + len(piece) > _MAX_TOTAL_CHARS:
            piece = piece[: max(0, _MAX_TOTAL_CHARS - total)] + "\n…(잘림)"
        chunks.append(piece)
        used.append(path)
        total += len(piece)
        if total >= _MAX_TOTAL_CHARS:
            break

    return ProjectContext(text="\n\n".join(chunks), sources=used)
